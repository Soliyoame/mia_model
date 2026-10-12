from __future__ import annotations
import argparse, json, math, re, unicodedata
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / 'artifacts/v25/development/shared_g_anchor_cohort_query_usable_100sample_50plus50_member_index_fixed_20261002'
DEFAULT_OUTPUT = ROOT / '研究记录/v25_shared_g_mechanism_review_20261003'
BOOTSTRAP_REPLICATES = 20000
BOOTSTRAP_SEED = 20261003
LOCAL_SLOT_COUNT = 3
INITIAL_GATE_POINTS = 1
SCORE_LAMBDA = 1.0
SCORE_CUTOFF = 2.0
LAMBDA_CANDIDATES = (0.5, 1.0, 1.5, 2.0)
SCORE_CUTOFF_CANDIDATES = (1.0, 2.0, 3.0, 4.0)

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def read_jsonl(path):
    with path.open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]

def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def normalize(value):
    trans = str.maketrans({'–':'-', '—':'-', '−':'-', '×':'x'})
    text = unicodedata.normalize('NFKC', str(value)).translate(trans).casefold()
    text = re.sub(r'[*_\x60]', '', text)
    text = re.sub(r'\s*([.,%/():\-])\s*', r'\1', text)
    text = re.sub(r'(?<=\d)\s+(?=\d)', '', text)
    return text

def response_label(response, answer, status='completed'):
    if status != 'completed' or not str(response or '').strip(): return 'invalid'
    text, target = normalize(response), normalize(answer)
    if re.search(r"\b(?:unknown|cannot|can't|not sure|unclear|don['’]t know|does not|doesn't|do not|don't|not contain|not specify|not provide|no information)\b", text, re.I):
        return 'ambiguous'
    pattern = re.escape(re.sub(r'\s+', ' ', target).strip()).replace(r'\ ', r'\s+')
    return 'correct' if pattern and re.search(rf'(?<![a-z0-9]){pattern}(?![a-z0-9])', text) else 'incorrect'

def exact_mcnemar_p(b, c):
    n = b + c
    if n == 0: return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / (2 ** n)
    return min(1.0, 2 * tail)

def pair_counts(rows):
    c = Counter((bool(r.get('anchored_correct')), bool(r.get('no_anchor_correct'))) for r in rows)
    return {'true,true': int(c[(True, True)]), 'true,false': int(c[(True, False)]), 'false,true': int(c[(False, True)]), 'false,false': int(c[(False, False)])}

def build_rows(root):
    plans, initials, followups, retrievals, generations = [read_jsonl(root / n) for n in ('query_plan.jsonl','initial_responses.jsonl','followup_responses.jsonl','retrieval.jsonl','generation.jsonl')]
    iby, fby, rby = ({r['query_id']: r for r in rows} for rows in (initials, followups, retrievals))
    gby = {r['source_key']: r for r in generations}
    by = {}
    for p in plans:
        key = (p['source_key'], int(p['slot_index']))
        row = by.setdefault(key, {'source_key':p['source_key'], 'dataset':p['dataset'], 'group':p['group'], 'slot_index':int(p['slot_index'])})
        arm = p['arm']
        if arm == 'initial':
            resp = iby[p['query_id']]
            lab = response_label(resp.get('response',''), p['answer'], resp.get('status','invalid'))
            row.update(initial_query_id=p['query_id'], initial_question=p['question'], initial_answer=p['answer'], initial_label=lab, initial_correct=lab=='correct', initial_response=resp.get('response',''))
        elif arm in ('anchored','no_anchor'):
            resp = fby.get(p['query_id'])
            lab = response_label(resp.get('response',''), p['answer'], resp.get('status','invalid')) if resp else None
            row.update(**{arm+'_query_id':p['query_id'], arm+'_question':p['question'], arm+'_answer':p['answer'], arm+'_label':lab, arm+'_correct':lab=='correct', arm+'_response':resp.get('response','') if resp else ''})
    for (source, slot), row in by.items():
        rec = gby[source]['records']
        row['anchor_text'] = rec['anchored_followups'][slot].get('anchor','')
        row['retrieval'] = {arm:rby[row[arm+'_query_id']] for arm in ('initial','anchored','no_anchor')}
    triggered = [r for r in by.values() if r.get('initial_correct')]
    return triggered, plans, generations, rby

def conditional(rows):
    out = {}
    for name, subset in [('ALL', rows), ('KB_Member',[r for r in rows if r['group']=='KB_Member']), ('True_Non_Member',[r for r in rows if r['group']=='True_Non_Member'])]:
        n=len(subset); a=sum(r['anchored_correct'] for r in subset); z=sum(r['no_anchor_correct'] for r in subset); pairs=pair_counts(subset)
        out[name]={'triggered_slots':n,'anchored_correct':a,'anchored_rate':a/n if n else None,'no_anchor_correct':z,'no_anchor_rate':z/n if n else None,'difference_pp':100*(a-z)/n if n else None,'paired_outcomes':pairs,'mcnemar_exact_two_sided_p':exact_mcnemar_p(pairs['true,false'],pairs['false,true'])}
    return out

def clusters(rows, group=None):
    subset = rows if group is None else [r for r in rows if r['group']==group]
    by=defaultdict(list)
    for r in subset: by[r['source_key']].append(r)
    out=[]
    for source, rs in sorted(by.items()):
        a=sum(r['anchored_correct'] for r in rs); z=sum(r['no_anchor_correct'] for r in rs); n=len(rs)
        out.append({'source_key':source,'group':rs[0]['group'],'dataset':rs[0]['dataset'],'trigger_count':n,'anchored_correct':a,'no_anchor_correct':z,'delta':(a-z)/n})
    return out

def bootstrap(rows, group=None):
    cs=clusters(rows, group)
    if not cs: return {'source_count':0,'triggered_slots':0,'weighted_delta':None,'ci95':[None,None]}
    t=np.array([c['trigger_count'] for c in cs],float); a=np.array([c['anchored_correct'] for c in cs],float); z=np.array([c['no_anchor_correct'] for c in cs],float)
    rng=np.random.default_rng(BOOTSTRAP_SEED); idx=rng.integers(0,len(cs),size=(BOOTSTRAP_REPLICATES,len(cs)))
    d=(a[idx].sum(1)-z[idx].sum(1))/t[idx].sum(1)
    sd=np.array([c['delta'] for c in cs]); nz=sd[sd!=0]; pos=int((nz>0).sum()); neg=int((nz<0).sum())
    p=1.0 if len(nz)==0 else min(1.0,2*sum(math.comb(len(nz),k) for k in range(min(pos,neg)+1))/(2**len(nz)))
    return {'source_count':len(cs),'triggered_slots':int(t.sum()),'anchored_correct':int(a.sum()),'no_anchor_correct':int(z.sum()),'weighted_delta':float((a.sum()-z.sum())/t.sum()),'source_level_mean_delta':float(sd.mean()),'ci95':[float(np.quantile(d,.025)),float(np.quantile(d,.975))],'bootstrap_replicates':BOOTSTRAP_REPLICATES,'bootstrap_seed':BOOTSTRAP_SEED,'nonzero_source_delta_count':int(len(nz)),'positive_source_delta_count':pos,'negative_source_delta_count':neg,'sign_test_exact_two_sided_p':p,'clusters':cs}

def rates(rows, rby):
    out={}
    for name, subset in [('ALL',rows),('KB_Member',[r for r in rows if r['group']=='KB_Member']),('True_Non_Member',[r for r in rows if r['group']=='True_Non_Member'])]:
        d={}
        for arm in ('initial','anchored','no_anchor'):
            total=len(subset); target=sum(bool(rby[r[arm+'_query_id']].get('target_source_chunk_ranks')) for r in subset); surface=sum(bool(rby[r[arm+'_query_id']].get('answer_surface_chunk_ranks')) for r in subset)
            d[arm+'_target_source']={'hits':target,'total':total,'rate':target/total if total else None}; d[arm+'_answer_surface']={'hits':surface,'total':total,'rate':surface/total if total else None}
        for field,key in [('target_source_chunk_ranks','target_source_pairs'),('answer_surface_chunk_ranks','answer_surface_pairs')]:
            c=Counter((bool(rby[r['anchored_query_id']].get(field)),bool(rby[r['no_anchor_query_id']].get(field))) for r in subset)
            d[key]={'true,true':int(c[(True,True)]),'true,false':int(c[(True,False)]),'false,true':int(c[(False,True)]),'false,false':int(c[(False,False)])}
        out[name]=d
    return out

def length_stats(rows):
    out={}
    for arm in ('initial','anchored','no_anchor'):
        v=[len(r[arm+'_question']) for r in rows]; out[arm]={'n':len(v),'mean_chars':float(np.mean(v)),'median_chars':float(np.median(v)),'min_chars':min(v),'max_chars':max(v)}
    v=[len(r['anchor_text']) for r in rows]; out['anchor_text']={'n':len(v),'mean_chars':float(np.mean(v)),'median_chars':float(np.median(v)),'min_chars':min(v),'max_chars':max(v)}
    return out

def region_stats(gens):
    rel=Counter(); diff=Counter(); all3=0; anyd=0
    for g in gens:
        d=g['records'].get('region_diagnostics',{}); rel[str(d.get('relation'))]+=1; diff[str(d.get('different_region_count'))]+=1
        if d.get('different_region_count')==3: all3+=1
        if isinstance(d.get('different_region_count'),int) and d['different_region_count']>0: anyd+=1
    return {'source_count':len(gens),'relation_counts':dict(rel),'different_region_count_counts':dict(diff),'all_three_local_regions_different_count':all3,'all_three_local_regions_different_rate':all3/len(gens),'any_local_region_different_count':anyd,'any_local_region_different_rate':anyd/len(gens),'policy':'different region preferred, not a hard construction gate'}

def matcher_diag(rows):
    mis=[r for r in rows if r['anchored_label']!=r['no_anchor_label']]
    return {'mismatch_count_all_triggered':len(mis),'mismatch_count_member_triggered':sum(r['group']=='KB_Member' for r in mis),'interpretation':'diagnostic only; labels are not rewritten after seeing responses','examples':[{'source_key':r['source_key'],'dataset':r['dataset'],'group':r['group'],'slot_index':r['slot_index'],'expected_answer':r['anchored_answer'],'anchored_label':r['anchored_label'],'no_anchor_label':r['no_anchor_label'],'anchored_response':r['anchored_response'].strip(),'no_anchor_response':r['no_anchor_response'].strip()} for r in mis]}

def false_positive_diagnostic(report, threshold=None):
    if threshold is None:
        threshold = float(report['metrics']['initial']['threshold'])
    rows = report['source_scores']
    initial_false_positives = {row['source_key'] for row in rows if row['group']=='True_Non_Member' and row['initial_score'] >= threshold}
    result = {'threshold': threshold, 'threshold_status':'reported development diagnostic threshold; not frozen for successor', 'initial_false_positive_sources':len(initial_false_positives)}
    for arm in ('anchored_chain','no_anchor_chain'):
        corrected = {row['source_key'] for row in rows if row['source_key'] in initial_false_positives and row[arm+'_score'] < threshold}
        positive = [row for row in rows if row[arm+'_score'] >= threshold]
        members = sum(row['group']=='KB_Member' for row in positive)
        nonmembers = sum(row['group']=='True_Non_Member' for row in positive)
        initial_members = sum(row['group']=='KB_Member' and row['initial_score'] >= threshold for row in rows)
        result[arm] = {'corrected_initial_false_positive_sources':len(corrected), 'correction_rate':len(corrected)/len(initial_false_positives) if initial_false_positives else None, 'fpr_before':len(initial_false_positives)/sum(row['group']=='True_Non_Member' for row in rows), 'fpr_after':nonmembers/sum(row['group']=='True_Non_Member' for row in rows), 'member_tpr_before':initial_members/sum(row['group']=='KB_Member' for row in rows), 'member_tpr_after':members/sum(row['group']=='KB_Member' for row in rows), 'member_retention_among_initial_positives':members/initial_members if initial_members else None, 'positive_source_count':len(positive), 'false_positive_source_keys_corrected':sorted(corrected)}
    result['interpretation'] = 'feasibility evidence only when the initial false-positive denominator is small'
    return result

def source_bit_rows(report):
    rows = []
    for source in report.get('source_scores', []):
        initial_bits = [int(bool(v)) for v in source.get('initial_bits', [])]
        anchored_bits = [int(bool(v)) for v in source.get('anchored_bits', [])]
        no_anchor_bits = [int(bool(v)) for v in source.get('no_anchor_bits', [])]
        if not all(len(bits) == LOCAL_SLOT_COUNT for bits in (initial_bits, anchored_bits, no_anchor_bits)):
            raise ValueError(f"source {source.get('source_key')} does not contain exactly {LOCAL_SLOT_COUNT} score bits")
        rows.append({
            'source_key': source['source_key'],
            'group': source['group'],
            'dataset': source['dataset'],
            'initial_bits': initial_bits,
            'anchored_bits': anchored_bits,
            'no_anchor_bits': no_anchor_bits,
            'initial_points': sum(initial_bits),
            'anchored_followup_points': sum(i * f for i, f in zip(initial_bits, anchored_bits)),
            'no_anchor_followup_points': sum(i * f for i, f in zip(initial_bits, no_anchor_bits)),
        })
    return rows

def auc_from_scores(rows, score_key):
    member = [float(row[score_key]) for row in rows if row['group'] == 'KB_Member']
    nonmember = [float(row[score_key]) for row in rows if row['group'] == 'True_Non_Member']
    if not member or not nonmember:
        return None
    wins = sum(score > negative for score in member for negative in nonmember)
    ties = sum(score == negative for score in member for negative in nonmember)
    return float((wins + 0.5 * ties) / (len(member) * len(nonmember)))

def score_distribution(rows, score_key):
    return {str(score): int(count) for score, count in sorted(Counter(row[score_key] for row in rows).items())}

def point_score_diagnostic(source_rows, lambda_value=SCORE_LAMBDA, cutoff=SCORE_CUTOFF):
    scored = []
    for row in source_rows:
        scored.append({
            'source_key': row['source_key'],
            'group': row['group'],
            'dataset': row['dataset'],
            'initial_points': row['initial_points'],
            'anchored_followup_points': row['anchored_followup_points'],
            'no_anchor_followup_points': row['no_anchor_followup_points'],
            'anchored_score': row['initial_points'] + lambda_value * row['anchored_followup_points'],
            'no_anchor_score': row['initial_points'] + lambda_value * row['no_anchor_followup_points'],
        })
    initial_positive = {row['source_key'] for row in scored if row['initial_points'] >= INITIAL_GATE_POINTS}
    initial_false_positives = {row['source_key'] for row in scored if row['group'] == 'True_Non_Member' and row['source_key'] in initial_positive}
    initial_member_positives = sum(row['group'] == 'KB_Member' and row['source_key'] in initial_positive for row in scored)
    total_members = sum(row['group'] == 'KB_Member' for row in scored)
    total_nonmembers = sum(row['group'] == 'True_Non_Member' for row in scored)
    arms = {}
    for arm in ('anchored', 'no_anchor'):
        score_key = f'{arm}_score'
        positive = {row['source_key'] for row in scored if row[score_key] >= cutoff}
        corrected = initial_false_positives - positive
        member_positive_count = sum(row['group'] == 'KB_Member' and row['source_key'] in positive for row in scored)
        nonmember_positive_count = sum(row['group'] == 'True_Non_Member' and row['source_key'] in positive for row in scored)
        arms[arm] = {
            'score_key': score_key,
            'positive_source_count': len(positive),
            'member_positive_count': member_positive_count,
            'nonmember_positive_count': nonmember_positive_count,
            'member_tpr': member_positive_count / total_members if total_members else None,
            'fpr_true_non_member': nonmember_positive_count / total_nonmembers if total_nonmembers else None,
            'accuracy': (member_positive_count + total_nonmembers - nonmember_positive_count) / len(scored) if scored else None,
            'auc': auc_from_scores(scored, score_key),
            'score_distribution_all': score_distribution(scored, score_key),
            'score_distribution_member': score_distribution([row for row in scored if row['group'] == 'KB_Member'], score_key),
            'score_distribution_true_non_member': score_distribution([row for row in scored if row['group'] == 'True_Non_Member'], score_key),
            'corrected_initial_false_positive_sources': len(corrected),
            'correction_rate': len(corrected) / len(initial_false_positives) if initial_false_positives else None,
            'member_retention_among_initial_positives': member_positive_count / initial_member_positives if initial_member_positives else None,
            'member_tpr_cost': (initial_member_positives / total_members - member_positive_count / total_members) if total_members else None,
            'false_positive_source_keys_corrected': sorted(corrected),
        }
    return {
        'lambda': float(lambda_value),
        'cutoff': float(cutoff),
        'formula': 'S_lambda = sum(I_i) + lambda * sum(I_i * F_i)',
        'initial_gate': f'sum(I_i) >= {INITIAL_GATE_POINTS}',
        'initial_positive_source_count': len(initial_positive),
        'initial_member_positive_count': initial_member_positives,
        'initial_false_positive_sources': len(initial_false_positives),
        'initial_false_positive_source_keys': sorted(initial_false_positives),
        'arms': arms,
        'source_scores': scored,
    }

def point_score_sensitivity(source_rows):
    grid = []
    for lambda_value in LAMBDA_CANDIDATES:
        for cutoff in SCORE_CUTOFF_CANDIDATES:
            diagnostic = point_score_diagnostic(source_rows, lambda_value, cutoff)
            grid.append({
                'lambda': float(lambda_value),
                'cutoff': float(cutoff),
                'anchored': {key: diagnostic['arms']['anchored'][key] for key in ('auc', 'corrected_initial_false_positive_sources', 'correction_rate', 'member_tpr', 'fpr_true_non_member', 'member_retention_among_initial_positives', 'member_tpr_cost')},
                'no_anchor': {key: diagnostic['arms']['no_anchor'][key] for key in ('auc', 'corrected_initial_false_positive_sources', 'correction_rate', 'member_tpr', 'fpr_true_non_member', 'member_retention_among_initial_positives', 'member_tpr_cost')},
            })
    return {
        'candidate_lambdas': [float(value) for value in LAMBDA_CANDIDATES],
        'candidate_cutoffs': [float(value) for value in SCORE_CUTOFF_CANDIDATES],
        'selected': {'lambda': SCORE_LAMBDA, 'cutoff': SCORE_CUTOFF},
        'selection_rule': 'lambda=1 gives one equal evidence point to a correct local fact and its gated remote recovery; cutoff=2 requires two total evidence points, either two local facts or one complete local-to-G chain.',
        'grid': grid,
    }

def plot_all(out, cond, summary, rows, rby, point_diag):
    figdir=out/'figures'; figdir.mkdir(parents=True,exist_ok=True)
    fig,ax=plt.subplots(1,2,figsize=(11,4.6),constrained_layout=True)
    gs=['KB_Member','True_Non_Member']; gate=[summary['input_report']['initial_correct_by_group'][g]/150 for g in gs]
    ax[0].bar([0,1],gate,color=['#2563eb','#94a3b8']); ax[0].set_xticks([0,1],['Member','Non-member']); ax[0].set_ylim(0,1); ax[0].set_ylabel('Initial correct rate'); ax[0].set_title('Initial correctness gate')
    for i,v in enumerate(gate): ax[0].text(i,v+.04,f'{v:.1%}',ha='center')
    x=np.arange(2); w=.34
    for off,arm,col in [(-w/2,'anchored','#0f766e'),(w/2,'no_anchor','#f59e0b')]:
        vals=[cond[g][arm+'_rate'] or 0 for g in gs]; ax[1].bar(x+off,vals,w,label=arm.replace('_','-'),color=col)
        for i,v in enumerate(vals): ax[1].text(i+off,v+.04,f'{v:.1%}',ha='center',fontsize=9)
    ax[1].set_xticks(x,['Member','Non-member']); ax[1].set_ylim(0,1); ax[1].set_ylabel('Correct rate | initial correct'); ax[1].set_title('Conditional G recovery'); ax[1].legend(frameon=False)
    fig.savefig(figdir/'gate_and_conditional_recovery.png',dpi=180); plt.close(fig)
    p=cond['ALL']['paired_outcomes']; mat=np.array([[p['false,false'],p['false,true']],[p['true,false'],p['true,true']]],float)
    fig,ax=plt.subplots(figsize=(5.4,4.8),constrained_layout=True); im=ax.imshow(mat,cmap='Blues'); ax.set_xticks([0,1],['No-anchor incorrect','No-anchor correct']); ax.set_yticks([0,1],['Anchored incorrect','Anchored correct']); ax.set_title('Paired follow-up outcomes\n(all triggered slots, n=89)')
    for i in range(2):
        for j in range(2): ax.text(j,i,int(mat[i,j]),ha='center',va='center',color='white' if mat[i,j]>mat.max()/2 else 'black',fontsize=14)
    fig.colorbar(im,ax=ax,shrink=.8,label='Slot count'); fig.savefig(figdir/'paired_followup_outcomes.png',dpi=180); plt.close(fig)
    m=[r for r in rows if r['group']=='KB_Member']; arms=['initial','anchored','no_anchor']; vals=[]
    for arm in arms: vals.append([sum(bool(rby[r[arm+'_query_id']].get('target_source_chunk_ranks')) for r in m)/len(m),sum(bool(rby[r[arm+'_query_id']].get('answer_surface_chunk_ranks')) for r in m)/len(m)])
    vals=np.asarray(vals); x=np.arange(2); fig,ax=plt.subplots(figsize=(7,4.6),constrained_layout=True)
    for i,(arm,col) in enumerate(zip(arms,['#64748b','#0f766e','#f59e0b'])):
        ax.bar(x+(i-1)*.24,vals[i],.24,label=arm.replace('_','-'),color=col)
        for j,v in enumerate(vals[i]): ax.text(j+(i-1)*.24,v+.025,f'{v:.1%}',ha='center',fontsize=9)
    ax.set_xticks(x,['target-source hit@5','answer-surface hit@5']); ax.set_ylim(0,1.1); ax.set_ylabel('Hit rate'); ax.set_title('Member triggered retrieval diagnostics (n=87)'); ax.legend(frameon=False); fig.savefig(figdir/'triggered_retrieval_hits.png',dpi=180); plt.close(fig)
    fp=point_diag; fig,ax=plt.subplots(1,2,figsize=(9,4.5),constrained_layout=True)
    arms=[('initial gate',fp['initial_false_positive_sources'] / max(1, sum(row['group'] == 'True_Non_Member' for row in fp['source_scores'])),fp['initial_member_positive_count'] / max(1, sum(row['group'] == 'KB_Member' for row in fp['source_scores'])),),('anchored score',fp['arms']['anchored']['fpr_true_non_member'],fp['arms']['anchored']['member_tpr']),('no-anchor score',fp['arms']['no_anchor']['fpr_true_non_member'],fp['arms']['no_anchor']['member_tpr'])]
    labels=[v[0] for v in arms]; colors=['#64748b','#0f766e','#f59e0b']; x=np.arange(len(labels))
    fpr=[v[1] for v in arms]; tpr=[v[2] for v in arms]
    ax[0].bar(x,fpr,color=colors); ax[0].set_xticks(x,labels,rotation=15); ax[0].set_ylim(0,0.06); ax[0].set_ylabel('FPR'); ax[0].set_title('Point-score false-positive correction')
    for i,v in enumerate(fpr): ax[0].text(i,v+0.002,f'{v:.1%}',ha='center',fontsize=9)
    ax[1].bar(x,tpr,color=colors); ax[1].set_xticks(x,labels,rotation=15); ax[1].set_ylim(0,1); ax[1].set_ylabel('Member TPR'); ax[1].set_title('Point-score recall tradeoff')
    for i,v in enumerate(tpr): ax[1].text(i,v+0.04,f'{v:.1%}',ha='center',fontsize=9)
    fig.savefig(figdir/'false_positive_correction_tradeoff.png',dpi=180); plt.close(fig)
    fig,ax=plt.subplots(1,2,figsize=(10,4.6),constrained_layout=True)
    score_values=sorted({row['anchored_score'] for row in point_diag['source_scores']} | {row['no_anchor_score'] for row in point_diag['source_scores']})
    for axis,arm,title,color in ((ax[0],'anchored','Anchored point scores','#0f766e'),(ax[1],'no_anchor','No-anchor point scores','#f59e0b')):
        for group,label,group_color in (('KB_Member','Member','#2563eb'),('True_Non_Member','True Non-member','#94a3b8')):
            counts=[sum(row['group'] == group and row[f'{arm}_score'] == value for row in point_diag['source_scores']) for value in score_values]
            axis.plot(score_values,counts,marker='o',label=label,color=group_color)
        axis.axvline(point_diag['cutoff'],color=color,linestyle='--',linewidth=1,label=f'cutoff={point_diag["cutoff"]:g}')
        axis.set_xticks(score_values); axis.set_xlabel('S_lambda'); axis.set_ylabel('Source count'); axis.set_title(title); axis.legend(frameon=False)
    fig.savefig(figdir/'point_score_distribution.png',dpi=180); plt.close(fig)

# Retained for auditability of the pre-score report; the executable entry point is main_scoring.
def legacy_threshold_main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',type=Path,default=DEFAULT_INPUT); ap.add_argument('--output',type=Path,default=DEFAULT_OUTPUT); args=ap.parse_args()
    rows, plans, gens, rby=build_rows(args.input); report=read_json(args.input/'report.json'); cond=conditional(rows); boot={'ALL':bootstrap(rows),'KB_Member':bootstrap(rows,'KB_Member'),'True_Non_Member':bootstrap(rows,'True_Non_Member')}; ret=rates(rows,rby); lens=length_stats(rows); reg=region_stats(gens); diag=matcher_diag(rows)
    initial_correct_by_group={g:sum(response_label(r['response'],next(p['answer'] for p in plans if p['query_id']==r['query_id']),r['status'])=='correct' for r in read_jsonl(args.input/'initial_responses.jsonl') if next(p for p in plans if p['query_id']==r['query_id'])['group']==g) for g in ('KB_Member','True_Non_Member')}
    fp_diag = false_positive_diagnostic(report)
    summary={'kind':'v25_shared_g_independent_mechanism_review','status':'development_only','no_formal_test_claim':True,'primary_endpoint_reframing':'false_positive_correction','input_artifact':str(args.input.relative_to(ROOT)) if args.input.is_relative_to(ROOT) else str(args.input),'input_report':{'source_count':report.get('source_count'),'group_counts':report.get('group_counts'),'metrics':{k:{'auc':report.get('metrics',{}).get(k,{}).get('AUC')} for k in ('initial','anchored_chain','no_anchor_chain')},'initial_correct_by_group':initial_correct_by_group},'counts':{'query_plan':len(plans),'initial_responses':len(read_jsonl(args.input/'initial_responses.jsonl')),'followup_responses':len(read_jsonl(args.input/'followup_responses.jsonl')),'retrieval_rows':len(read_jsonl(args.input/'retrieval.jsonl')),'generation_rows':len(gens),'triggered_slots':len(rows),'triggered_slots_by_group':dict(Counter(r['group'] for r in rows))},'conditional_recovery':cond,'source_cluster_bootstrap':boot,'retrieval_diagnostics':ret,'query_length_diagnostics':lens,'answer_matcher_diagnostics':diag,'region_diagnostics':reg,'false_positive_correction_diagnostic':fp_diag,'interpretation':{'main_finding':'initial True_Non_Member false positives are rejected by both follow-up arms; this is feasibility evidence, not a stable correction-rate estimate','chain_auc_limitation':'chain score contains initial correctness gate and is not a pure anchor effect','nonmember_interaction':'unestimable because only two True_Non_Member slots triggered','next_step':'new development identity with correct_anchor and remote_only as core correction arms; same_source_permuted_anchor is optional attribution control'}}
    design={'kind':'v25_shared_g_successor_control_design','status':'design_only_not_run','primary_endpoint':'false_positive_correction','endpoint_reframing':'The successor need not prove a stable positive anchor gain; it tests whether follow-up rejects source-level True_Non_Member false positives.','preserve':{'initial_gate':'initial_response_is_correct_per_slot','shared_G':'one frozen remote target per source reused by all follow-up arms','runtime_rule':'conditional sending only; no conditional query construction','source_level_unit':True},'core_required_arms':[{'arm':'correct_anchor','definition':'canonical e_i answer inserted into same-slot follow-up','purpose':'primary false-positive correction arm'},{'arm':'remote_only','definition':'same G question without local anchor','purpose':'control for generic follow-up rejection without local anchor'}],'optional_attribution_arms':[{'arm':'same_source_permuted_anchor','definition':'another local fact from same source; fixed cyclic mapping e1<-e2, e2<-e3, e3<-e1','purpose':'secondary attribution control; distinguish correct pairing from arbitrary source-local cue, extra length, or template specificity'}],'optional_matched_controls':[{'arm':'cross_source_matched_anchor','definition':'same dataset and fact type, length-matched anchor from another source','purpose':'source specificity diagnostic on matched subset'},{'arm':'neutral_length_matched','definition':'natural length-matched template without semantic source cue','purpose':'query length diagnostic only if frozen before calls'}],'budget':{'initial_calls_per_source':3,'core_followup_arms':2,'optional_followup_arms':1,'max_calls_per_source_core':9,'max_calls_per_source_with_permuted_control':12,'formula_core':'3 + 2 * sum(initial_correct)','formula_with_permuted_control':'3 + 3 * sum(initial_correct)','note':'correct_anchor and remote_only are core; same_source_permuted_anchor is optional attribution control; all variants require a new successor identity'},'primary_metrics':{'false_positive_set':'True_Non_Member sources with S_initial >= frozen tau','correction_indicator':'1[S_initial >= tau and S_followup < tau]','false_positive_correction_rate':'corrected initial false positives / initial false positives','fpr_before_after':'FPR at the same frozen tau before and after follow-up','member_retention':'Member sources positive after follow-up / Member sources positive initially','reporting_rule':'Report exact counts and uncertainty; do not call 2/2 a stable population rate.'},'freeze_before_victim':['source split and source/text hashes','e1/e2/e3, G, evidence spans and region relation','slot-to-anchor mapping for every arm','query text and hashes','frozen tau and minimum initial false-positive capacity','canonical answer aliases and ambiguous policy','retriever/index/model identity','source-cluster statistics and Holm correction plan'],'decision_rules':['the primary success criterion is pre-registered reduction of initial True_Non_Member false positives at the same frozen tau','report member retention and TPR cost alongside every false-positive correction result','correct_anchor versus remote_only is an attribution comparison, not a requirement for a stable G-recovery gain','same_source_permuted_anchor is secondary attribution evidence and may be run on a matched subset','if the initial false-positive set is too small, report feasibility only and do not claim a stable correction rate','do not relabel current responses after seeing them; parser changes belong to successor freeze'],'multiple_comparison':'pre-specify Holm correction only if optional attribution arms are included'}
    args.output.mkdir(parents=True,exist_ok=True); write_json(args.output/'review_summary.json',summary); write_json(args.output/'control_design.json',design); plot_all(args.output,cond,summary,rows,rby)
    print(json.dumps({'output':str(args.output),'triggered_slots':len(rows),'conditional_difference_pp':cond['ALL']['difference_pp'],'member_bootstrap_ci95':boot['KB_Member']['ci95']},ensure_ascii=False,indent=2))

def main_scoring():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',type=Path,default=DEFAULT_INPUT); ap.add_argument('--output',type=Path,default=DEFAULT_OUTPUT); args=ap.parse_args()
    rows, plans, gens, rby=build_rows(args.input)
    report=read_json(args.input/'report.json')
    source_rows=source_bit_rows(report)
    cond=conditional(rows)
    boot={'ALL':bootstrap(rows),'KB_Member':bootstrap(rows,'KB_Member'),'True_Non_Member':bootstrap(rows,'True_Non_Member')}
    ret=rates(rows,rby); lens=length_stats(rows); reg=region_stats(gens); diag=matcher_diag(rows)
    initial_responses=read_jsonl(args.input/'initial_responses.jsonl')
    plan_by_id={plan['query_id']:plan for plan in plans}
    initial_correct_by_group={
        group:sum(
            response_label(response['response'],plan_by_id[response['query_id']]['answer'],response['status']) == 'correct'
            for response in initial_responses
            if plan_by_id[response['query_id']]['group'] == group
        )
        for group in ('KB_Member','True_Non_Member')
    }
    point_diag=point_score_diagnostic(source_rows)
    sensitivity=point_score_sensitivity(source_rows)
    historical_fp_diag=false_positive_diagnostic(report)
    summary={
        'kind':'v25_shared_g_independent_mechanism_review',
        'status':'development_only',
        'no_formal_test_claim':True,
        'primary_endpoint_reframing':'source_level_point_score_with_false_positive_correction_as_operational_diagnostic',
        'input_artifact':str(args.input.relative_to(ROOT)) if args.input.is_relative_to(ROOT) else str(args.input),
        'input_report':{
            'source_count':report.get('source_count'),
            'group_counts':report.get('group_counts'),
            'metrics':{key:{'auc':report.get('metrics',{}).get(key,{}).get('AUC')} for key in ('initial','anchored_chain','no_anchor_chain')},
            'initial_correct_by_group':initial_correct_by_group,
        },
        'counts':{
            'query_plan':len(plans),
            'initial_responses':len(initial_responses),
            'followup_responses':len(read_jsonl(args.input/'followup_responses.jsonl')),
            'retrieval_rows':len(read_jsonl(args.input/'retrieval.jsonl')),
            'generation_rows':len(gens),
            'triggered_slots':len(rows),
            'triggered_slots_by_group':dict(Counter(r['group'] for r in rows)),
        },
        'conditional_recovery':cond,
        'source_cluster_bootstrap':boot,
        'retrieval_diagnostics':ret,
        'query_length_diagnostics':lens,
        'answer_matcher_diagnostics':diag,
        'region_diagnostics':reg,
        'point_score_diagnostic':point_diag,
        'point_score_parameter_sensitivity':sensitivity,
        'historical_threshold_diagnostic':historical_fp_diag,
        'interpretation':{
            'main_finding':'With equal point weights, the selected score retains more Member sources than the old chain-threshold rule while rejecting both development True_Non_Member false positives at the selected operational cutoff.',
            'score_interpretation':'Each correct local fact contributes one point; each correct gated probe of the shared remote target contributes one additional point. The latter is not an independent fact because all probes share G.',
            'parameter_status':'lambda=1 and cutoff=2 are development-calibrated candidates. They must be frozen before successor victim responses and must not be tuned on formal results.',
            'chain_auc_limitation':'The historical chain score contains the initial correctness gate and is retained only as an audit comparison.',
            'nonmember_interaction':'Unestimable because only two True_Non_Member sources triggered a follow-up in this development artifact.',
            'next_step':'Freeze the point-score rule in a new development identity with correct_anchor and remote_only as core arms; report source-level scores, AUC, FPR/TPR, and the cutoff diagnostic together.',
        },
    }
    design={
        'kind':'v25_shared_g_successor_control_design',
        'status':'design_only_not_run',
        'primary_endpoint':'source_level_point_score',
        'endpoint_reframing':'The successor uses a cumulative evidence score. False-positive correction is an operational diagnostic at a frozen cutoff, not the definition of the score.',
        'score_rule':{
            'formula':'S_lambda(s) = sum_i I_i(s) + lambda * sum_i I_i(s) F_i(s)',
            'lambda':SCORE_LAMBDA,
            'lambda_interpretation':'one equal evidence point for a correct local fact and one for its gated recovery of the shared G',
            'maximum_score':LOCAL_SLOT_COUNT * (1 + SCORE_LAMBDA),
            'initial_gate_points':INITIAL_GATE_POINTS,
            'operational_cutoff':SCORE_CUTOFF,
            'cutoff_interpretation':'at least two total evidence points: two local hits, or one local hit plus its correct gated G recovery',
            'parameter_selection':'development calibration plus an interpretable equal-weight rule; no formal victim response was used',
        },
        'preserve':{
            'initial_gate':'initial response is evaluated per slot',
            'shared_G':'one frozen remote target per source reused by all follow-up arms',
            'runtime_rule':'conditional sending only; no conditional query construction',
            'source_level_unit':True,
        },
        'core_required_arms':[
            {'arm':'correct_anchor','definition':'canonical e_i answer inserted into same-slot follow-up','purpose':'primary point-score evidence arm'},
            {'arm':'remote_only','definition':'same G question without local anchor','purpose':'control for generic follow-up rejection without local anchor'},
        ],
        'optional_attribution_arms':[
            {'arm':'same_source_permuted_anchor','definition':'another local fact from same source; fixed cyclic mapping e1<-e2, e2<-e3, e3<-e1','purpose':'secondary attribution control; distinguish correct pairing from arbitrary source-local cue, extra length, or template specificity'},
        ],
        'optional_matched_controls':[
            {'arm':'cross_source_matched_anchor','definition':'same dataset and fact type, length-matched anchor from another source','purpose':'source specificity diagnostic on matched subset'},
            {'arm':'neutral_length_matched','definition':'natural length-matched template without semantic source cue','purpose':'query length diagnostic only if frozen before victim calls'},
        ],
        'budget':{
            'initial_calls_per_source':3,
            'core_followup_arms':2,
            'optional_followup_arms':1,
            'max_calls_per_source_core':9,
            'max_calls_per_source_with_permuted_control':12,
            'formula_core':'3 + 2 * sum(initial_correct)',
            'formula_with_permuted_control':'3 + 3 * sum(initial_correct)',
            'note':'correct_anchor and remote_only are core; same_source_permuted_anchor is optional attribution control; all variants require a new successor identity',
        },
        'primary_metrics':{
            'source_score':'S_lambda as the primary source-level score',
            'score_auc':'AUC of S_lambda without post-hoc threshold selection',
            'operational_false_positive_set':'True_Non_Member sources with sum(I_i) >= frozen initial_gate_points',
            'correction_indicator':'1[initial gate positive and S_lambda < frozen operational cutoff]',
            'false_positive_correction_rate':'corrected initial false positives / initial false positives',
            'fpr_tpr':'Report FPR and Member TPR at the same frozen operational cutoff',
            'member_retention':'Member sources positive after the cutoff / Member sources positive at the initial gate',
            'reporting_rule':'Report exact counts, score distributions, AUC, and uncertainty; do not call 2/2 a stable population rate.',
        },
        'freeze_before_victim':[
            'source split and source/text hashes',
            'e1/e2/e3, G, evidence spans and region relation',
            'slot-to-anchor mapping for every arm',
            'query text and hashes',
            'lambda, initial gate points and operational score cutoff',
            'canonical answer aliases and ambiguous policy',
            'retriever/index/model identity',
            'source-cluster statistics and Holm correction plan',
        ],
        'decision_rules':[
            'the primary result is the frozen source-level point score and its AUC',
            'use the cutoff only for the pre-registered false-positive correction diagnostic',
            'report Member retention and TPR cost alongside every correction result',
            'correct_anchor versus remote_only is an attribution comparison, not a requirement for a stable G-recovery gain',
            'same_source_permuted_anchor is secondary attribution evidence and may be run on a matched subset',
            'if the initial false-positive set is too small, report feasibility only and do not claim a stable correction rate',
            'do not relabel current responses after seeing them; parser changes belong to successor freeze',
        ],
        'multiple_comparison':'pre-specify Holm correction only if optional attribution arms are included',
    }
    args.output.mkdir(parents=True,exist_ok=True)
    write_json(args.output/'review_summary.json',summary)
    write_json(args.output/'control_design.json',design)
    plot_all(args.output,cond,summary,rows,rby,point_diag)
    print(json.dumps({'output':str(args.output),'triggered_slots':len(rows),'selected_lambda':SCORE_LAMBDA,'selected_cutoff':SCORE_CUTOFF,'anchored_auc':point_diag['arms']['anchored']['auc'],'no_anchor_auc':point_diag['arms']['no_anchor']['auc'],'member_bootstrap_ci95':boot['KB_Member']['ci95']},ensure_ascii=False,indent=2))

# 主线与消融复用同一份三值赋分及输入校验。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.evaluation.source_scoring import (
    SIGNED_ARMS, SIGNED_GROUPS, SIGNED_FORMAL_REFUSAL_REASONS,
    unique_records, signed_outcome, validate_signed_lambdas, signed_score_bounds,
    signed_formal_outcome, signed_formal_features, load_signed_formal,
    signed_nli_formal_features, load_signed_nli_formal,
)

SIGNED_LAMBDAS = (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 4.0)


def signed_source_features(
    items: list[dict[str, Any]], predictions: list[dict[str, Any]],
    plans: list[dict[str, Any]], responses: list[dict[str, Any]],
    sources: list[dict[str, Any]], formal_sources: list[dict[str, Any]],
    cohort: str,
) -> list[dict[str, Any]]:
    from src.utils.hash import sha256_obj, sha256_text

    selected = [item for item in items if item['cohort'] == cohort]
    if not selected:
        raise ValueError('empty_development_cohort')
    iby = unique_records([dict(item, query_id=item['query']['query_id']) for item in selected], 'query_id')
    pby, rby, sby, jby = (unique_records(rows, key) for rows, key in (
        (plans, 'query_id'), (responses, 'query_id'), (sources, 'source_key'), (predictions, 'query_id')))
    formal_keys = {row['source_key'] for row in formal_sources}
    formal_hashes = {row[field] for row in formal_sources for field in ('source_hash', 'normalized_text_hash')}
    selected_keys = sorted({item['query']['source_key'] for item in selected})
    identity_owners: dict[str, str] = {}
    for key in selected_keys:
        source = sby[key]
        if source['group'] not in SIGNED_GROUPS:
            raise ValueError('unsupported_membership_group')
        hashes = {source['source_hash'], source['normalized_text_hash']}
        if not all(isinstance(value, str) and value for value in hashes):
            raise ValueError('missing_source_hash')
        if key in formal_keys or hashes & formal_hashes:
            raise ValueError('development_formal_source_overlap')
        for value in hashes:
            if value in identity_owners and identity_owners[value] != key:
                raise ValueError('duplicate_source_identity')
            identity_owners[value] = key

    outcomes = {}
    for query_id, item in iby.items():
        query, response = item['query'], item['response']
        source = sby[query['source_key']]
        judgment = jby[query_id]['judgment']
        outcome = signed_outcome(judgment)
        binding = judgment['binding']
        if query['arm'] == 'correct_anchor':
            paired = item.get('paired_query', {})
            paired_id = paired.get('query_id')
            if (paired_id not in pby or paired != pby[paired_id] or paired.get('arm') != 'remote_only'
                    or any(query.get(field) != paired.get(field) for field in ('source_key', 'slot_index', 'answer', 'claim'))
                    or item.get('paired_query_sha256') != sha256_obj(paired)
                    or binding.get('paired_query_id') != paired_id or binding.get('paired_query_sha256') != sha256_obj(paired)):
                raise ValueError('paired_target_binding_drift')
        qhash, rhash = sha256_obj(query), sha256_text(response['response'])
        if (query_id not in pby or query_id not in rby
                or sha256_obj(pby[query_id]) != qhash
                or sha256_obj(rby[query_id]) != sha256_obj(response)
                or any(response[field] != query[field] for field in ('query_id', 'source_key', 'arm', 'slot_index'))
                or any(query[field] != source[field] for field in ('dataset', 'group'))
                or item['source_hash'] != source['source_hash']
                or item['query_sha256'] != qhash or item['response_sha256'] != rhash
                or response.get('status') != 'completed' or not response['response'].strip()
                or any(binding.get(field) != expected for field, expected in {
                    'query_id': query_id, 'source_key': query['source_key'],
                    'source_hash': source['source_hash'], 'original_query_sha256': qhash,
                    'response_sha256': rhash,
                }.items())):
            raise ValueError(f'saved_input_identity_drift:{query_id}')
        outcomes[query_id] = outcome

    result = []
    for key in selected_keys:
        source = sby[key]
        source_plans = [query for query in plans if query['source_key'] == key]
        coordinates = {(query['arm'], query['slot_index']): query for query in source_plans}
        expected = {(arm, slot) for arm in ('initial', *SIGNED_ARMS) for slot in range(3)}
        if len(source_plans) != 9 or set(coordinates) != expected:
            raise ValueError(f'incomplete_or_duplicate_source_slots:{key}')
        if any(query['dataset'] != source['dataset'] or query['group'] != source['group'] for query in source_plans):
            raise ValueError('source_plan_identity_drift')
        initial_ids = [coordinates['initial', slot]['query_id'] for slot in range(3)]
        if any(query_id not in outcomes for query_id in initial_ids):
            raise ValueError(f'incomplete_initial_source:{key}')
        initial = [outcomes[query_id] for query_id in initial_ids]
        row = {field: source[field] for field in ('source_key', 'dataset', 'group', 'source_hash', 'normalized_text_hash')}
        row.update(initial_correct=initial.count(1), initial_refused=initial.count(-1),
                   initial_wrong=initial.count(0), initial_outcomes=initial, initial_query_ids=initial_ids, arms={})
        for arm in SIGNED_ARMS:
            observed, missing, ignored, gated_ids = [], [], [], []
            for slot in range(3):
                query_id = coordinates[arm, slot]['query_id']
                # -1 的布尔值为真；门控必须显式检查答对，不能使用 bool(outcome)。
                if initial[slot] == 1:
                    gated_ids.append(query_id)
                    if query_id in outcomes:
                        observed.append(outcomes[query_id])
                    else:
                        missing.append({'query_id': query_id, 'reason':
                                        'missing_saved_judgment' if query_id in rby else 'missing_response'})
                elif query_id in outcomes:
                    ignored.append(query_id)
            row['arms'][arm] = {
                'correct': observed.count(1), 'refused': observed.count(-1), 'wrong': observed.count(0),
                'missing': len(missing), 'missing_queries': missing, 'gated_query_ids': gated_ids,
                'historical_outside_gate': ignored,
            }
        row['complete'] = all(row['arms'][arm]['missing'] == 0 for arm in SIGNED_ARMS)
        result.append(row)
    return result


def signed_coverage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for dataset in sorted({row['dataset'] for row in rows}):
        for group in SIGNED_GROUPS:
            subset = [row for row in rows if row['dataset'] == dataset and row['group'] == group]
            result.append({
                'dataset': dataset, 'group': group, 'sources': len(subset),
                'complete_sources': sum(row['complete'] for row in subset),
                'sources_with_backfill': sum(row.get('backfill_responses', 0) > 0 for row in subset),
                'initial_correct': sum(row['initial_correct'] for row in subset),
                'initial_refused': sum(row['initial_refused'] for row in subset),
                'initial_wrong': sum(row['initial_wrong'] for row in subset),
                'arms': {arm: {field: sum(row['arms'][arm][field] for row in subset)
                               for field in ('correct', 'refused', 'wrong', 'missing')} for arm in SIGNED_ARMS},
            })
    return result


def paired_signed_grid(
    rows: list[dict[str, Any]], lambdas: list[float], replicates: int, seed: int,
) -> list[dict[str, Any]]:
    """数据集与身份内整篇来源配对抽样；所有公式和权重共用抽样权重。"""
    from src.evaluation.metrics import roc_auc

    lambdas = validate_signed_lambdas(lambdas)
    if replicates < 2 or 0.0 not in lambdas:
        raise ValueError('bootstrap_needs_replicates_and_lambda_zero_baseline')
    rows = sorted(rows, key=lambda row: row['source_key'])
    if not rows or len({row['source_key'] for row in rows}) != len(rows):
        raise ValueError('empty_or_duplicate_source_sample')
    columns = [(arm, weight, method) for arm in SIGNED_ARMS for weight in lambdas for method in ('old', 'new')]
    scores = np.empty((len(rows), len(columns)))
    for i, row in enumerate(rows):
        for j, (arm, weight, method) in enumerate(columns):
            lower, upper = signed_score_bounds(row, arm, weight, method)
            if lower != upper:
                raise ValueError('missing_followup_has_no_point_score')
            scores[i, j] = lower
    estimates, samples = {}, {}
    rng = np.random.default_rng(seed)
    for dataset in sorted({row['dataset'] for row in rows}):
        positions = {group: [i for i, row in enumerate(rows) if row['dataset'] == dataset and row['group'] == group]
                     for group in SIGNED_GROUPS}
        positive, negative = (scores[positions[group]] for group in SIGNED_GROUPS)
        m, n = len(positive), len(negative)
        if m < 2 or n < 2:
            raise ValueError(f'insufficient_sources_for_stratified_bootstrap:{dataset}')
        positive, positive_counts = np.unique(positive, axis=0, return_counts=True)
        negative, negative_counts = np.unique(negative, axis=0, return_counts=True)
        wins = (positive[:, None, :] > negative[None, :, :]).astype(float)
        wins += 0.5 * (positive[:, None, :] == negative[None, :, :])
        estimates[dataset] = np.einsum('i,ijk,j->k', positive_counts, wins, negative_counts) / (m * n)
        # 合并完整得分向量相同的来源只为加速；抽样总数仍为原始 source 数。
        # 多项分布的聚合性质保留来源 bootstrap 分布及全部方法间的配对关系。
        mw = rng.multinomial(m, positive_counts / m, size=replicates)
        nw = rng.multinomial(n, negative_counts / n, size=replicates)
        samples[dataset] = np.einsum('bi,ijk,bj->bk', mw, wins, nw, optimize=True) / (m * n)
        for j in range(len(columns)):
            check = roc_auc([{'group': rows[i]['group'], 'score': scores[i, j]}
                             for i in positions[SIGNED_GROUPS[0]] + positions[SIGNED_GROUPS[1]]], 'score')
            if not math.isclose(float(check), float(estimates[dataset][j]), abs_tol=1e-12):
                raise AssertionError('auc_crosscheck_failed')
    estimates['macro'] = np.mean(list(estimates.values()), axis=0)
    samples['macro'] = np.mean(list(samples.values()), axis=0)

    def interval(values: np.ndarray) -> list[float]:
        return np.quantile(values, [0.025, 0.975]).tolist()

    grid = []
    for arm in SIGNED_ARMS:
        for weight in lambdas:
            old, new = (columns.index((arm, weight, method)) for method in ('old', 'new'))
            entry: dict[str, Any] = {'arm': arm, 'lambda': weight, 'per_dataset': {}}
            for dataset, point in estimates.items():
                delta = float(point[new] - point[old])
                delta_samples = samples[dataset][:, new] - samples[dataset][:, old]
                metrics = {'old': {'auc': float(point[old]), 'ci95': interval(samples[dataset][:, old])},
                           'new': {'auc': float(point[new]), 'ci95': interval(samples[dataset][:, new])},
                           'delta_auc': delta, 'delta_ci95': interval(delta_samples)}
                for method, column in (('old', old), ('new', new)):
                    zero = columns.index((arm, 0.0, method))
                    metrics[method]['gain_over_initial'] = float(point[column] - point[zero])
                    metrics[method]['gain_over_initial_ci95'] = interval(samples[dataset][:, column] - samples[dataset][:, zero])
                if dataset == 'macro':
                    entry['macro'] = metrics
                    if weight == 1.0:
                        entry['primary_test'] = {
                            'null': 'macro_delta_auc_equals_zero',
                            'method': 'two_sided_centered_paired_stratified_bootstrap_approximation',
                            'p_raw': float((1 + np.count_nonzero(np.abs(delta_samples - delta) >= abs(delta) - 1e-12)) / (replicates + 1)),
                            'replicates': replicates,
                        }
                else:
                    entry['per_dataset'][dataset] = metrics
            grid.append(entry)
    tests = [entry['primary_test'] for entry in grid if 'primary_test' in entry]
    running = 0.0
    for rank, test in enumerate(sorted(tests, key=lambda test: test['p_raw'])):
        running = max(running, min(1.0, (len(tests) - rank) * test['p_raw']))
        test['p_holm_two_arms'] = running
    return grid


def signed_auc_bounds(rows: list[dict[str, Any]], lambdas: list[float]) -> list[dict[str, Any]]:
    from src.evaluation.metrics import roc_auc

    result = []
    for arm in SIGNED_ARMS:
        for weight in validate_signed_lambdas(lambdas):
            entry: dict[str, Any] = {'arm': arm, 'lambda': weight, 'per_dataset': {}}
            for dataset in sorted({row['dataset'] for row in rows}):
                subset = [row for row in rows if row['dataset'] == dataset]
                bounds = {}
                for method in ('old', 'new'):
                    values = [signed_score_bounds(row, arm, weight, method) for row in subset]
                    lower = [{'group': row['group'], 'score': value[0 if row['group'] == 'KB_Member' else 1]}
                             for row, value in zip(subset, values)]
                    upper = [{'group': row['group'], 'score': value[1 if row['group'] == 'KB_Member' else 0]}
                             for row, value in zip(subset, values)]
                    bounds[method] = [roc_auc(lower, 'score'), roc_auc(upper, 'score')]
                    if any(value is None for value in bounds[method]):
                        raise ValueError('bounds_require_both_membership_groups')
                entry['per_dataset'][dataset] = bounds
            entry['macro'] = {method: np.mean([value[method] for value in entry['per_dataset'].values()], axis=0).tolist()
                              for method in ('old', 'new')}
            entry['macro']['conservative_delta_range'] = [entry['macro']['new'][0] - entry['macro']['old'][1],
                                                         entry['macro']['new'][1] - entry['macro']['old'][0]]
            result.append(entry)
    return result


def signed_operating_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from src.evaluation.metrics import clopper_pearson_interval, rates_at_threshold, threshold_curve, tpr_at_fpr_details

    result = []
    for arm in SIGNED_ARMS:
        for method in ('old', 'new'):
            for dataset in sorted({row['dataset'] for row in rows}):
                subset = [dict(row, score=signed_score_bounds(row, arm, 1.0, method)[0])
                          for row in rows if row['dataset'] == dataset]
                fixed = rates_at_threshold(subset, 2.0, 'score')
                curve = threshold_curve(subset, 'score')
                low_fpr = []
                for target in (0.01, 0.05):
                    point = tpr_at_fpr_details(curve, target)
                    point['FPR_CI95_conditional_on_threshold'] = clopper_pearson_interval(point['false_positive_count'], point['negative_count'])
                    low_fpr.append(point)
                descriptions = {}
                for group in SIGNED_GROUPS:
                    values = [row['score'] for row in subset if row['group'] == group]
                    descriptions[group] = {'n': len(values), 'mean': float(np.mean(values)), 'source_sd': float(np.std(values, ddof=1)),
                                           'distribution': {str(value): count for value, count in sorted(Counter(values).items())}}
                result.append({'arm': arm, 'method': method, 'dataset': dataset, 'lambda': 1.0,
                               'fixed_cutoff': fixed, 'low_fpr': low_fpr, 'descriptive_scores': descriptions})
    return result


def signed_secondary_metrics(rows: list[dict[str, Any]], replicates: int, seed: int) -> dict[str, Any]:
    """固定 λ=1/cutoff=2 的配对次要指标；AP 按召回增量积分，不用梯形近似。"""
    from src.evaluation.metrics import clopper_pearson_interval, threshold_curve, tpr_at_fpr_details

    rows = sorted(rows, key=lambda row: row['source_key'])
    if replicates < 2 or not rows or len({row['source_key'] for row in rows}) != len(rows):
        raise ValueError('invalid_secondary_bootstrap_sample')
    columns = [(arm, method) for arm in SIGNED_ARMS for method in ('old', 'new')]
    values = []
    for row in rows:
        vector = [signed_score_bounds(row, arm, 1.0, method) for arm, method in columns]
        if any(lower != upper for lower, upper in vector):
            raise ValueError('missing_followup_has_no_point_score')
        values.append([lower for lower, _ in vector])
    scores = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    result: dict[str, Any] = {'lambda': 1.0, 'cutoff': 2.0, 'bootstrap_replicates': replicates,
                              'bootstrap_seed': seed, 'statistical_unit': 'source_document',
                              'average_precision_definition': 'non_interpolated_recall_increment_weighted_precision',
                              'zero_denominator_convention': 0.0, 'entries': [], 'contrasts': []}

    def divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
        return np.divide(numerator, denominator, out=np.zeros_like(numerator, dtype=float), where=denominator != 0)

    def interval(samples: np.ndarray) -> list[float]:
        return np.quantile(samples, [0.025, 0.975]).tolist()

    for dataset in sorted({row['dataset'] for row in rows}):
        positions = {group: [i for i, row in enumerate(rows) if row['dataset'] == dataset and row['group'] == group]
                     for group in SIGNED_GROUPS}
        m, n = (len(positions[group]) for group in SIGNED_GROUPS)
        if min(m, n) < 2:
            raise ValueError('insufficient_sources_for_secondary_bootstrap')
        positive, pc = np.unique(scores[positions[SIGNED_GROUPS[0]]], axis=0, return_counts=True)
        negative, nc = np.unique(scores[positions[SIGNED_GROUPS[1]]], axis=0, return_counts=True)
        mw = np.vstack([pc, rng.multinomial(m, pc / m, size=replicates)])
        nw = np.vstack([nc, rng.multinomial(n, nc / n, size=replicates)])
        distributions = {}
        for column, (arm, method) in enumerate(columns):
            tp = (mw @ (positive[:, column] >= 2)).astype(float)
            fp = (nw @ (negative[:, column] >= 2)).astype(float)
            tn, fn = n - fp, m - tp
            metrics = {'accuracy': (tp + tn) / (m + n), 'balanced_accuracy': (tp / m + tn / n) / 2,
                       'precision': divide(tp, tp + fp), 'recall': tp / m, 'specificity': tn / n,
                       'fpr': fp / n, 'fnr': fn / m, 'f1': divide(2 * tp, 2 * tp + fp + fn),
                       'npv': divide(tn, tn + fn),
                       'mcc': divide(tp * tn - fp * fn, np.sqrt((tp + fp) * m * n * (tn + fn)))}
            levels = np.unique(np.r_[positive[:, column], negative[:, column]])[::-1]
            ph = mw @ (positive[:, column, None] == levels)
            nh = nw @ (negative[:, column, None] == levels)
            ctp, cfp = ph.cumsum(axis=1), nh.cumsum(axis=1)
            metrics['average_precision'] = np.sum((ph / m) * divide(ctp, ctp + cfp), axis=1)
            distributions[arm, method] = metrics
            scored = [{'group': rows[i]['group'], 'score': float(scores[i, column])}
                      for group in SIGNED_GROUPS for i in positions[group]]
            curve, low_fpr = threshold_curve(scored, 'score'), []
            for target in (0.0, 0.001, 0.01, 0.05):
                point = tpr_at_fpr_details(curve, target)
                selected = next(row for row in curve if row['threshold'] == point['threshold'])
                point.update(true_positive_count=selected['true_positive_count'], positive_count=m)
                point['TPR_CI95_conditional_on_threshold'] = clopper_pearson_interval(point['true_positive_count'], m)
                point['FPR_CI95_conditional_on_threshold'] = clopper_pearson_interval(point['false_positive_count'], n)
                low_fpr.append(point)
            result['entries'].append({
                'dataset': dataset, 'arm': arm, 'method': method, 'positive_count': m, 'negative_count': n,
                'metrics': {name: {'estimate': float(sample[0]), 'ci95': interval(sample[1:])} for name, sample in metrics.items()},
                'confusion': {'true_positive_count': int(tp[0]), 'false_positive_count': int(fp[0]),
                              'true_negative_count': int(tn[0]), 'false_negative_count': int(fn[0])}, 'low_fpr': low_fpr,
            })
        for arm in SIGNED_ARMS:
            for name, old in distributions[arm, 'old'].items():
                delta = distributions[arm, 'new'][name] - old
                result['contrasts'].append({'dataset': dataset, 'arm': arm, 'metric': name,
                                            'delta': float(delta[0]), 'ci95': interval(delta[1:])})
    return result


def load_signed_development(
    cohort: Path, inputs_path: Path, predictions_path: Path, formal_manifest: Path,
    backfill: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    from src.utils.hash import sha256_file

    run, frozen = (read_json(cohort / name) for name in ('run_config.json', 'query_freeze.json'))
    if run.get('development_only') is not True or run.get('source_unit') != 'source_document':
        raise ValueError('development_source_document_inputs_required')
    protocol = run['config']['query_protocol']
    if (protocol['local_slots'] != 3 or set(protocol['arms']) != set(SIGNED_ARMS)
            or protocol['followup_gate'] != 'initial_response_correct_per_slot'):
        raise ValueError('unsupported_development_query_protocol')
    for names in (run['artifacts'], frozen['artifacts']):
        for name, expected in names.items():
            if sha256_file(cohort / name) != expected:
                raise ValueError(f'development_artifact_drift:{name}')
    prediction = read_json(predictions_path)
    if prediction['version'] != 'binary_target_rules_nli_v3':
        raise ValueError('fixed_v3_predictions_required')
    calibration = predictions_path.parent / 'calibration.json'
    saved_module = predictions_path.parent / (prediction['version'] + '.py')
    for path, expected in ((inputs_path, prediction['input_sha256']), (calibration, prediction['calibration_sha256']),
                           (saved_module, prediction['module_sha256'])):
        if sha256_file(path) != expected:
            raise ValueError(f'saved_judgment_artifact_drift:{path.name}')
    items = read_jsonl(inputs_path)
    all_ids = [item['query']['query_id'] for item in items]
    jby = unique_records(prediction['rows'], 'query_id')
    if len(set(all_ids)) != len(all_ids) or set(all_ids) != set(jby):
        raise ValueError('input_prediction_coverage_mismatch')
    if any(row['judgment']['version'] != prediction['version'] for row in prediction['rows']):
        raise ValueError('mixed_judgment_versions')
    sources = read_jsonl(cohort / 'source_manifest.jsonl')
    plans = read_jsonl(cohort / 'query_plan.jsonl')
    responses = read_jsonl(cohort / 'initial_responses.jsonl') + read_jsonl(cohort / 'followup_responses.jsonl')
    formal = read_jsonl(formal_manifest)
    features = signed_source_features(items, prediction['rows'], plans, responses, sources, formal, cohort.name)
    original_complete = sum(row['complete'] for row in features)
    original_missing = {query['query_id'] for row in features for arm in SIGNED_ARMS
                        for query in row['arms'][arm]['missing_queries']}
    backfill_metadata: dict[str, Any] = {'response_records': 0, 'original_complete_sources': original_complete,
                                       'original_missing_followups': len(original_missing), 'model_statistics': {}}
    extra_paths = []
    if backfill is not None:
        extra_paths = [backfill / name for name in ('followup_responses.jsonl', 'judgment_inputs.jsonl', 'predictions.json')]
        added_responses, added_items = read_jsonl(extra_paths[0]), read_jsonl(extra_paths[1])
        added_predictions = read_json(extra_paths[2])
        added_ids = set(unique_records(added_responses, 'query_id'))
        if (not added_ids <= original_missing or len(added_items) != len(added_ids)
                or {item['query']['query_id'] for item in added_items} != added_ids
                or any(item['cohort'] != cohort.name for item in added_items)
                or set(unique_records(added_predictions['rows'], 'query_id')) != added_ids
                or added_predictions['input_sha256'] != sha256_file(extra_paths[1])
                or any(added_predictions[field] != prediction[field]
                       for field in ('version', 'module_sha256', 'calibration_sha256', 'config'))
                or any(row['judgment']['version'] != prediction['version'] for row in added_predictions['rows'])
                or any(row.get('fixed_gate_predictions_sha256') != sha256_file(predictions_path) for row in added_responses)):
            raise ValueError('backfill_identity_or_judgment_drift')
        items += added_items
        responses += added_responses
        features = signed_source_features(items, prediction['rows'] + added_predictions['rows'], plans, responses, sources, formal, cohort.name)
        additions = Counter(row['source_key'] for row in added_responses)
        for row in features:
            row['backfill_responses'] = additions[row['source_key']]
        backfill_metadata.update(response_records=len(added_responses), model_statistics=added_predictions['model_statistics'],
                                 per_dataset=dict(Counter(item['query']['dataset'] for item in added_items)),
                                 called_at_min=min(row['called_at'] for row in added_responses),
                                 called_at_max=max(row['called_at'] for row in added_responses))
        failed = backfill / 'predictions_missing_paired_target.json'
        if failed.exists():
            previous = read_json(failed)
            previous_inputs = backfill / 'judgment_inputs_missing_paired_target.jsonl'
            if previous['input_sha256'] != sha256_file(previous_inputs):
                raise ValueError('preserved_failed_prediction_input_drift')
            extra_paths.extend([failed, previous_inputs])
            backfill_metadata['superseded_prediction_attempt'] = {
                'status': 'invalid_input_adapter_missing_paired_target',
                'invalid_records': sum(row['judgment']['status'] == 'invalid' for row in previous['rows']),
                'model_statistics': previous['model_statistics'], 'predictions': str(failed),
            }
    selected = [item for item in items if item['cohort'] == cohort.name]
    model_ids = Counter(item['response'].get('provider_model_id') for item in selected)
    if set(model_ids) != {run['runtime']['concrete_model']}:
        raise ValueError('mixed_or_mismatched_provider_model')
    index = read_json(cohort / 'index_manifest.json')
    index_keys = {source['source_key'] for source in index['sources']}
    if index.get('index_member_only') is not True or any(source['group'] != 'KB_Member' for source in index['sources']):
        raise ValueError('nonmember_in_recorded_index')
    if any((row['source_key'] in index_keys) != (row['group'] == 'KB_Member') for row in features):
        raise ValueError('membership_index_mismatch')
    used = [inputs_path, predictions_path, calibration, saved_module, formal_manifest] + extra_paths
    used += [cohort / name for name in ('source_manifest.jsonl', 'query_plan.jsonl', 'initial_responses.jsonl',
                                      'followup_responses.jsonl', 'run_config.json', 'query_freeze.json', 'index_manifest.json')]
    used += [cohort / name for name in frozen['artifacts']]
    hashes = {str(path.resolve()): sha256_file(path) for path in used}
    metadata = {
        'cohort': cohort.name, 'original_manifest_sources': len(sources), 'query_usable_sources': len({row['source_key'] for row in plans}),
        'saved_judgment_input_sources_all_cohorts': len({item['query']['source_key'] for item in items}),
        'selected_sources': len(features), 'selected_response_records': len(selected),
        'selection': 'exact_cohort_name_in_preexisting_fixed_v3_inputs; no outcome_based_selection_in_this_analysis',
        'original_seed': run['config']['seed'], 'original_code_commit': run['code_commit'],
        'runtime': run['runtime'], 'prediction_version': prediction['version'], 'prediction_config': prediction['config'],
        'prediction_module_sha256': prediction['module_sha256'],
        'backfill': backfill_metadata,
        'provider_model_ids': dict(model_ids),
        'system_fingerprints': dict(Counter(str(item['response'].get('system_fingerprint')) for item in selected)),
        'formal_isolation': {'formal_sources': len(formal), 'source_key_overlap': 0, 'cross_field_text_hash_overlap': 0,
                             'formal_responses_or_metrics_read': False},
    }
    return features, metadata, hashes


def cached_missing_requests(
    features: list[dict[str, Any]], plans: list[dict[str, Any]], retrievals: list[dict[str, Any]],
    index_sources: list[dict[str, Any]], plan_hash: str, template: str,
) -> list[dict[str, Any]]:
    from src.utils.hash import sha256_obj, sha256_text

    pby, rby = unique_records(plans, 'query_id'), unique_records(retrievals, 'query_id')
    members = unique_records(index_sources, 'source_key')
    if any(row['group'] != 'KB_Member' for row in index_sources):
        raise ValueError('nonmember_in_recorded_index')
    result = []
    for source in features:
        for arm in SIGNED_ARMS:
            for missing in source['arms'][arm]['missing_queries']:
                if missing['reason'] != 'missing_response':
                    raise ValueError('missing_judgment_must_not_resend_existing_response')
                query_id = missing['query_id']
                query, retrieval = pby[query_id], rby[query_id]
                ordered_members = [row for row in index_sources if row['dataset'] == query['dataset']]
                if (retrieval['query_plan_sha256'] != plan_hash
                        or retrieval['index_identity'] != sha256_obj([(row['source_key'], row['source_hash']) for row in ordered_members])
                        or any(retrieval[field] != query[field] for field in ('source_key', 'dataset', 'arm', 'slot_index'))):
                    raise ValueError('cached_retrieval_identity_drift')
                for chunk in retrieval['retrieved_chunks']:
                    member = members.get(chunk['source_key'])
                    if not member or member['dataset'] != query['dataset'] or member['source_hash'] != chunk['source_hash']:
                        raise ValueError('cached_retrieval_nonmember_or_hash_drift')
                context = '\n\n---\n\n'.join(chunk['text'] for chunk in retrieval['retrieved_chunks'])
                prompt = template.format(contexts=context, query=query['question'])
                if sha256_text(context) != retrieval['context_sha256'] or sha256_text(prompt) != retrieval['prompt_sha256']:
                    raise ValueError('cached_prompt_or_context_drift')
                result.append({'query': query, 'prompt': prompt, 'prompt_sha256': retrieval['prompt_sha256'],
                               'source_hash': source['source_hash']})
    return sorted(result, key=lambda row: (row['query']['dataset'], row['query']['source_key'], row['query']['slot_index'], row['query']['arm']))


def run_missing_development(
    cohort: Path, predictions_path: Path, features: list[dict[str, Any]], output: Path,
    dataset: str, max_new: int,
) -> dict[str, Any]:
    """单库顺序补问；每次调用前后保存状态，不覆盖旧响应或重发不确定请求。"""
    import ast
    from src.llm.factory import build_victim_client, llm_profile_identity, load_llm_profiles
    from src.llm.response_validation import detect_api_error_text
    from src.utils.hash import sha256_file, sha256_obj, sha256_text
    from src.utils.io import write_jsonl_atomic

    if max_new < 1 or dataset not in {row['dataset'] for row in features}:
        raise ValueError('invalid_backfill_cell_or_budget')
    run = read_json(cohort / 'run_config.json')
    template_tree = ast.parse((ROOT / 'scripts/95_run_v25_shared_g_pilot.py').read_text(encoding='utf-8'))
    template = next(ast.literal_eval(node.value) for node in template_tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'RAG_PROMPT' for target in node.targets))
    if sha256_text(template) != run['prompts']['rag_sha256']:
        raise ValueError('frozen_rag_template_drift')
    queries = read_jsonl(cohort / 'query_plan.jsonl')
    plan = cached_missing_requests(features, queries, read_jsonl(cohort / 'retrieval.jsonl'),
                                   read_json(cohort / 'index_manifest.json')['sources'], sha256_file(cohort / 'query_plan.jsonl'), template)
    planned = {row['query']['query_id']: row for row in plan}
    response_path = output / 'followup_responses.jsonl'
    saved = unique_records(read_jsonl(response_path), 'query_id') if response_path.exists() else {}
    retrieval_hash, gate_hash = sha256_file(cohort / 'retrieval.jsonl'), sha256_file(predictions_path)
    profile_expected = run['model_profiles']['victim']
    for query_id, row in saved.items():
        if (query_id not in planned or row['status'] != 'completed'
                or row['response_sha256'] != sha256_text(row['response'])
                or row['retrieval_sha256'] != retrieval_hash or row['fixed_gate_predictions_sha256'] != gate_hash
                or row['prompt_sha256'] != planned[query_id]['prompt_sha256']
                or row['provider_model_id'] != profile_expected['model'] or row['profile_identity'] != profile_expected
                or any(row[field] != planned[query_id]['query'][field] for field in ('source_key', 'arm', 'slot_index'))):
            raise ValueError('backfill_resume_drift_or_uncertain_response')
    pending = [row for row in plan if row['query']['dataset'] == dataset and row['query']['query_id'] not in saved][:max_new]
    if pending and (output / 'predictions.json').exists():
        raise ValueError('cannot_extend_already_judged_backfill')
    client = None
    if pending:
        profiles = load_llm_profiles({'llm_profiles_path': run['runtime']['llm_profiles_path']})
        client, profile = build_victim_client(profiles, profile_name=run['runtime']['victim_profile'])
        if llm_profile_identity(profile) != profile_expected:
            raise ValueError('backfill_effective_model_profile_drift')
        output.mkdir(parents=True, exist_ok=True)
    for request in pending:
        query = request['query']
        row = {field: query[field] for field in ('query_id', 'source_key', 'arm', 'slot_index')}
        row.update(status='attempt_started', retrieval_sha256=retrieval_hash,
                   prompt_sha256=request['prompt_sha256'], fixed_gate_predictions_sha256=gate_hash)
        saved[query['query_id']] = row
        write_jsonl_atomic(list(saved.values()), response_path)
        try:
            response = client.generate_with_metadata(request['prompt'], temperature=run['runtime']['generation']['temperature'],
                                                      max_tokens=run['runtime']['generation']['max_tokens'], timeout=profile['timeout'])
            status = 'completed'
            if response.provider_model_id != profile_expected['model']:
                status = 'provider_model_drift'
            elif not response.content.strip() or detect_api_error_text(response.content):
                status = 'invalid_response'
            row.update(status=status, response=response.content, response_sha256=sha256_text(response.content),
                       provider_model_id=response.provider_model_id, provider_request_id=response.provider_request_id,
                       called_at=response.called_at, system_fingerprint=response.system_fingerprint, profile_identity=profile_expected)
        except Exception as error:
            row.update(status='uncertain_transport', error_type=type(error).__name__)
        write_jsonl_atomic(list(saved.values()), response_path)
        print(json.dumps({'dataset': dataset, 'completed_total': sum(value['status'] == 'completed' for value in saved.values()),
                          'planned_total': len(plan), 'status': row['status']}), flush=True)
        if row['status'] != 'completed':
            raise RuntimeError('backfill_failed_preserved_without_automatic_resend')
        time.sleep(run['runtime']['generation']['request_interval_seconds'])
    inputs = []
    remote_by_slot = {(query['source_key'], query['slot_index']): query for query in queries if query['arm'] == 'remote_only'}
    for request in plan:
        query = request['query']
        if query['query_id'] in saved:
            response = saved[query['query_id']]
            item = {'query': query, 'response': response, 'source_hash': request['source_hash'],
                    'query_sha256': sha256_obj(query), 'response_sha256': response['response_sha256'],
                    'cohort': cohort.name, 'stage': 'development_followup_backfill', 'prior_use': 'newly_collected_missing_followup'}
            if query['arm'] == 'correct_anchor':
                paired = remote_by_slot[query['source_key'], query['slot_index']]
                item.update(paired_query=paired, paired_query_sha256=sha256_obj(paired))
            inputs.append(item)
    if inputs:
        input_path = output / 'judgment_inputs.jsonl'
        if (output / 'predictions.json').exists() and read_json(output / 'predictions.json')['input_sha256'] != sha256_file(input_path):
            raise ValueError('backfill_predictions_bound_to_changed_inputs')
        if (output / 'predictions.json').exists() and read_jsonl(input_path) != inputs:
            raise ValueError('cannot_extend_already_judged_backfill')
        write_jsonl_atomic(inputs, input_path)
    return {'dataset': dataset, 'new_calls': len(pending), 'completed_total': len(saved), 'planned_total': len(plan)}


def signed_figures(output: Path, report: dict[str, Any]) -> None:
    directory = output / 'figures'
    directory.mkdir()
    formal = report['status'] == 'posthoc_formal_score_diagnostic'
    datasets = sorted({row['dataset'] for row in report['coverage']})
    metric_name = datasets[0] if len(datasets) == 1 else 'Macro'
    scope = 'Post-hoc formal-data diagnostic' if formal else 'Development only'
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    for column, arm in enumerate(SIGNED_ARMS):
        grid = [row for row in report['complete_case_grid'] if row['arm'] == arm]
        x = np.arange(len(grid))
        for method, color, offset in (('old', '#4c78a8', -0.06), ('new', '#008b78', 0.06)):
            points = np.array([row['macro'][method]['auc'] for row in grid])
            bounds = np.array([row['macro'][method]['ci95'] for row in grid])
            axes[0, column].errorbar(x + offset, points, yerr=np.maximum(0, np.array([points - bounds[:, 0], bounds[:, 1] - points])),
                                    fmt='o-', capsize=3, color=color, label=method)
        delta = np.array([100 * row['macro']['delta_auc'] for row in grid])
        ci = 100 * np.array([row['macro']['delta_ci95'] for row in grid])
        axes[1, column].errorbar(x, delta, yerr=np.maximum(0, np.array([delta - ci[:, 0], ci[:, 1] - delta])),
                                fmt='o-', capsize=3, color='#7c4a9e')
        axes[1, column].axhline(0, color='#777777', linewidth=1, linestyle='--')
        for axis in axes[:, column]:
            axis.set_xticks(x, [f"{row['lambda']:g}" for row in grid])
            axis.set_xlabel('Lambda (fixed grid)')
            axis.grid(axis='y', alpha=0.18)
        axes[0, column].set_title(arm.replace('_', ' '))
        axes[0, column].set_ylabel(f'{metric_name} ROC-AUC')
        axes[0, column].legend(frameon=False)
        axes[0, column].set_ylim(top=1.02)
        axes[1, column].set_ylabel('New - old AUC (percentage points)')
    fig.suptitle(f"{scope}: {report['complete_sources']} complete sources\nPaired source bootstrap 95% intervals")
    for extension in ('png', 'pdf'):
        fig.savefig(directory / f'formula_comparison.{extension}', dpi=180)
    plt.close(fig)

    coverage = report['coverage']
    x = np.arange(len(coverage))
    labels = [row['dataset'] + '\n' + ('M' if row['group'] == 'KB_Member' else 'N') for row in coverage]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True)
    complete = np.array([row['complete_sources'] for row in coverage])
    backfilled = np.array([row['sources_with_backfill'] for row in coverage])
    missing = np.array([row['sources'] - row['complete_sources'] for row in coverage])
    axes[0].bar(x, complete - backfilled, color='#4c78a8', label='Complete before backfill')
    axes[0].bar(x, backfilled, bottom=complete - backfilled, color='#008b78', label='Completed by backfill')
    if np.any(missing):
        axes[0].bar(x, missing, bottom=complete, color='#e69550', label='Still missing follow-up')
    for i, (full, absent) in enumerate(zip(complete, missing)):
        axes[0].text(i, full + absent + 0.2, f'{full}/{full + absent}', ha='center', fontsize=9)
    axes[0].set_ylabel('Source count (label = complete / all)')
    axes[0].set_ylim(0, max(complete + missing) * 1.3)
    bottom = np.zeros(len(coverage))
    for field, label, color in (('initial_correct', 'Correct', '#008b78'), ('initial_wrong', 'Other (0)', '#a6a6a6'),
                                ('initial_refused', 'Refused', '#e69550')):
        values = np.array([row[field] / (3 * row['sources']) for row in coverage])
        axes[1].bar(x, values, bottom=bottom, color=color, label=label)
        bottom += values
    axes[1].set_ylabel('Initial outcome fraction (3 slots / source)')
    axes[1].set_ylim(0, 1.2)
    for axis in axes:
        axis.set_xticks(x, labels, fontsize=9)
        axis.legend(frameon=False, fontsize=9)
    axes[0].set_title('Completeness by dataset and membership')
    nli = report['metadata'].get('correctness_matcher') == 'binary_target_rules_nli_v3'
    axes[1].set_title('Fixed v3 labels; descriptive slot counts' if nli or not formal else 'Original correctness and refusal reasons')
    fig.suptitle(f"Coverage and refusal signal: {report['selected_sources']} sources; M = member, N = non-member\n{scope}")
    for extension in ('png', 'pdf'):
        fig.savefig(directory / f'coverage_and_refusals.{extension}', dpi=180)
    plt.close(fig)


def signed_markdown(output: Path, report: dict[str, Any]) -> None:
    def ci(value: list[float]) -> str:
        return f'[{value[0]:.6f}, {value[1]:.6f}]'

    primary = [row for row in report['complete_case_grid'] if row['lambda'] == 1.0]
    formal = report['status'] == 'posthoc_formal_score_diagnostic'
    datasets = sorted({row['dataset'] for row in report['coverage']})
    metric_name = datasets[0] if len(datasets) == 1 else 'macro'
    scope = '正式数据事后诊断' if formal else '开发集离线对照'
    nli = report['metadata'].get('correctness_matcher') == 'binary_target_rules_nli_v3'
    label_description = '固定 v3 判定' if nli or not formal else '原有正确性判定、复核标签及拒答理由'
    baseline_description = ('旧分数由已保存的 v3 标签和门控离线重建，当前没有完整旧公式报告可逐项复现'
                            if report['metadata'].get('baseline_origin') == 'reconstructed_from_saved_v3_judgments'
                            else '旧分数逐项复算一致')
    lines = [
        f'# 三值新公式的{scope}', '',
        f"**状态：{report['status']}；未选定新权重，未替换正式评分。**", '',
        f'比较问题：在同一批{label_description}和同一正确性门控下，拒答扣分能否改善 source-level 成员推断排序？', '',
        '`old = C + λR`；`new = (C − U) + λ(R − V)`。C/U 是三次初问答对/拒答数；R/V 是仅初问答对才纳入的追问答对/拒答数。其他未答对为0；不归一化；两个追问臂分别评分。', '',
        (f"本批实际为 {report['selected_sources']} 篇正式来源；{report['complete_sources']} 篇初问与门控追问完整。两类样本数见下表，直接使用原批次全部来源；{baseline_description}。"
         if formal else f"已保存 v3 输入中该 cohort 有 {report['selected_sources']} 篇来源；{report['complete_sources']} 篇有完整追问，可作同样本配对比较。原始 cohort 的其余来源未纳入，多个历史 cohort 未混合。"), '',
        '| 数据集 | 身份 | 全部来源 | 完整来源 | 缺失来源 | 初问拒答 / 3N |',
        '|---|---|---:|---:|---:|---:|',
    ]
    for row in report['coverage']:
        lines.append(f"| {row['dataset']} | {row['group']} | {row['sources']} | {row['complete_sources']} | {row['sources'] - row['complete_sources']} | {row['initial_refused']}/{3 * row['sources']} |")
    if nli:
        lines += ['', '拒答只取已保存 v3 判分的 `reason=refused`，`correct` 为+1，其余有效 `not_correct` 为0。没有重新调用判分器或读入旧 Assistant 修正；无效/缺失不能填0。两种公式共享同一套 v3 标签，追问仍仅由初问答对触发。', '']
    elif formal:
        lines += ['', '拒答沿用原匹配器的 `abstention_without_answer` / `explicit_abstention_outside_answer` 理由；已复核为正确者仍计+1。`ambiguous` 不整体映射为拒答：语义争议、否定冲突及其他非拒答未确认正确回答保留0。没有应用 SciDocs 的 NLI v3 判分或重新决定正确性。', '']
    lines += ['', '## 主要对照：λ=1', '', 'AUC 越高越好。区间为固定模型条件下、数据集×身份分层的来源配对 bootstrap 95% 区间。多数据集时等权macro，不跨库合并来源；单数据集只报告该库结果。', '',
              '| 追问臂 | 数据集 | 旧 AUC [95% CI] | 新 AUC [95% CI] | ΔAUC [95% CI] |', '|---|---|---|---|---|']
    for entry in primary:
        summaries = list(entry['per_dataset'].items()) + ([('macro', entry['macro'])] if len(datasets) > 1 else [])
        for name, values in summaries:
            lines.append(f"| {entry['arm']} | {name} | {values['old']['auc']:.6f} {ci(values['old']['ci95'])} | {values['new']['auc']:.6f} {ci(values['new']['ci95'])} | {values['delta_auc']:+.6f} {ci(values['delta_ci95'])} |")
    lines += ['', '## 固定网格敏感性', '', '延续此前开发比较的 λ=1 主对照与固定网格；所有结果只作描述性敏感性分析，不据此选择正式λ。区间非同时置信带，不能选择最高点作为验证结论。', '',
              f'| 追问臂 | λ | 旧 {metric_name} AUC | 新 {metric_name} AUC | 新−旧 | 新相对自身 λ=0 的增量 |', '|---|---:|---:|---:|---:|---:|']
    for entry in report['complete_case_grid']:
        value = entry['macro']
        lines.append(f"| {entry['arm']} | {entry['lambda']:g} | {value['old']['auc']:.6f} | {value['new']['auc']:.6f} | {value['delta_auc']:+.6f} | {value['new']['gain_over_initial']:+.6f} |")
    if not formal or report['complete_sources'] != report['selected_sources']:
        lines += ['', '## 全部来源的缺失界限', '',
                  '以下是尚未观测追问可取答对/答错/拒答时的 AUC 识别界限，**不是置信区间**，不补零、不假设随机缺失。每个公式分别取 Member 最坏、Non-member 最好得到下界，反向得到上界。新旧差异范围用两者端点保守相减，未利用两种公式共享缺失结果的约束。', '',
                  f'| 追问臂 | λ | 旧 {metric_name} AUC 界限 | 新 {metric_name} AUC 界限 | 保守 Δ 范围 |', '|---|---:|---|---|---|']
        for entry in report['all_source_bounds']:
            values = entry['macro']
            lines.append(f"| {entry['arm']} | {entry['lambda']:g} | {ci(values['old'])} | {ci(values['new'])} | {ci(values['conservative_delta_range'])} |")
    initial = report['all_source_initial_grid'][0]['macro']
    lines += ['', f"λ=0 不使用追问，全部 {report['selected_sources']} 篇均可精确评分：旧 {metric_name} AUC={initial['old']['auc']:.6f} {ci(initial['old']['ci95'])}，新={initial['new']['auc']:.6f} {ci(initial['new']['ci95'])}；配对差值={initial['delta_auc']:+.6f} {ci(initial['delta_ci95'])}。", '',
              '## 解释与边界', '']
    for entry in primary:
        values = entry['macro']
        direction = '上升' if values['delta_auc'] > 0 else ('下降' if values['delta_auc'] < 0 else '不变')
        evidence = '跨过或包含0' if values['delta_ci95'][0] <= 0 <= values['delta_ci95'][1] else '未包含0'
        lines.append(f"- {entry['arm']}：λ=1 的 {metric_name} AUC {direction} {abs(values['delta_auc']) * 100:.3f} 个百分点，配对区间{evidence}。此判断条件于本批来源与固定判分器。")
    lines += [f'- {limit}' for limit in report['limitations']]
    secondary = report.get('secondary_metrics_lambda1')
    if secondary:
        lines += ['', '## λ=1：其他指标与代价', '',
                  '固定 score≥2 判为成员。AP是非插值 Average Precision，与阈值无关；其余本表指标使用该固定阈值。Precision和AP条件于本批成员比例。', '',
                  '| 追问臂 | 公式 | Acc | Precision | Recall | F1 | MCC | AP | FP / FN |',
                  '|---|---|---:|---:|---:|---:|---:|---:|---|']
        for entry in secondary['entries']:
            values, counts = entry['metrics'], entry['confusion']
            lines.append(f"| {entry['arm']} | {entry['method']} | " + ' | '.join(f"{100 * values[name]['estimate']:.2f}%" for name in ('accuracy', 'precision', 'recall', 'f1'))
                         + f" | {values['mcc']['estimate']:.6f} | {values['average_precision']['estimate']:.6f} | {counts['false_positive_count']} / {counts['false_negative_count']} |")
        lines += ['', '| 追问臂 | 公式 | 零经验误报 TPR | TPR@≤0.1% | TPR@≤1% | TPR@≤5% |',
                  '|---|---|---:|---:|---:|---:|']
        for entry in secondary['entries']:
            lines.append(f"| {entry['arm']} | {entry['method']} | " + ' | '.join(f"{point['TPR']:.2%}" for point in entry['low_fpr']) + ' |')
        lines += ['', '低FPR采用实际可达的ROC阈值，不插值；不同方法在同一FPR上限下的实际FPR未必相同。所有区间、配对差值及具体阈值见统计附录与 `other_metrics_lambda1.json`。', '']
    lines += ['', '## 图与复现', '',
              '![新旧公式与配对差值](figures/formula_comparison.png)', '',
              f'图1读法：上排是逐权重新旧 {metric_name} AUC，下排直接显示配对差值及区间。先看 λ=1，再看趋势是否稳定；不能把不同权重的小波动当作新的独立检验。', '',
              '![来源覆盖与拒答分布](figures/coverage_and_refusals.png)', '',
              '图2读法：左侧区分原有完整来源、补问后完整来源和仍缺失来源，右侧显示新增扣分信号来自何处。槽位比例只作描述，推断统计的样本量始终是来源数。', '',
              '完整参数、输入与代码 hash、逐数据集界限及逐来源计数见 `report.json`、`source_features.jsonl`。检验与低FPR细节见 `stats-appendix.md`。', '',
              '```powershell', report['reproduction_command'], '```', '',
              f"输出目录已存在时拒绝覆盖；复现时使用新的空输出目录。本次新增victim调用 {report['new_calls']['victim']} 次，评分统计阶段无模型调用，Retriever调用为0。", '']
    (output / 'analysis-report.md').write_text('\n'.join(lines), encoding='utf-8')

    stats = ['# 统计附录', '',
             f"固定模型/索引/查询构造来自1次历史运行，本次属于{scope}。原seed={report['metadata']['original_seed']}，本次另补 {report['new_calls']['victim']} 条缺失追问；来源bootstrap={report['bootstrap_replicates']}次，seed={report['bootstrap_seed']}。无多seed或多模型重复。", '',
             '样本单位为 source document。每个数据集内 Member 与 Non-member 分别有放回抽样，每篇来源的初问、两个追问臂、全部权重和新旧公式始终一起抽样。每个重复先算逐库 AUC，再等权平均；并列得分计0.5。CI为2.5%/97.5%经验分位数。', '',
             '为加速，将同一身份层内完整方法得分向量相同的来源合并，以类型频率为概率、原始来源数为总数做多项抽样。这与逐来源有放回抽样的分布等价；类型数不作为样本量。', '',
             '效应量为新−旧 AUC 及其百分点评价。另给出每种公式相对自身 λ=0 的配对增量。分数均值/样本标准差描述来源间差异，不是run间方差。', '',
             f'没有使用正态性或方差齐性假设。λ=1 检验 H0: {metric_name} ΔAUC=0；将配对bootstrap差值中心化，近似双侧 p=(1+#{{|Δ*−Δhat|≥|Δhat|}})/(B+1)。它不是精确随机化检验，不要求新旧原始分数可互换；两个追问臂的 p 用 Holm 校正。其余网格不作显著性筛选。', '',
             '假设：来源在每个数据集×身份层内可交换抽样，数据集视为固定。小样本、离散分数或经验AUC达到1时，bootstrap区间可能退化；CI/p不覆盖判分器误差、缺失选择偏差、开发选择、模型/index变化或其他数据集泛化。所有推断仅作探索性证据，不作为正式验收。', '',
             f'| 追问臂 | Δ{metric_name} AUC | 配对95% CI | 近似双侧 p | Holm p（2臂） |', '|---|---:|---|---:|---:|']
    for entry in primary:
        stats.append(f"| {entry['arm']} | {entry['macro']['delta_auc']:+.6f} | {ci(entry['macro']['delta_ci95'])} | {entry['primary_test']['p_raw']:.6f} | {entry['primary_test']['p_holm_two_arms']:.6f} |")
    stats += ['', '## λ=1：逐库固定阈值与低FPR诊断', '',
              '固定 cutoff=2 只是沿用历史数值的操作点诊断，未重新校准。因为新−旧分数=−U−λV≤0，同阈值下预测Member集合只会缩小；FPR下降必须与TPR损失一起看。', '',
              'TPR@1%/5%使用真实经验ROC点，不插值；观察阈值不是总体FPR保证。下面的FPR精确区间条件于所展示阈值，不校正ROC选择。各库最小非零FPR为：' + '；'.join(f"{row['dataset']} {1 / row['sources']:.4%}（n={row['sources']}）" for row in report['coverage'] if row['group'] == 'True_Non_Member') + '。', '',
              '| 追问臂 | 公式 | 数据集 | cutoff=2 Acc / TPR / FPR | TPR@1% / @5% | 1%操作点阈值 | 观察FPR [95% CP] |', '|---|---|---|---|---|---|---|']
    for entry in report['operating_points_lambda1']:
        fixed, low = entry['fixed_cutoff'], entry['low_fpr']
        stats.append(f"| {entry['arm']} | {entry['method']} | {entry['dataset']} | {fixed['Accuracy']:.6f} / {fixed['TPR']:.6f} / {fixed['FPR']:.6f} | {low[0]['TPR']:.6f} / {low[1]['TPR']:.6f} | {low[0]['threshold']} | {low[0]['achieved_FPR']:.6f} {ci(low[0]['FPR_CI95_conditional_on_threshold'])} |")
    stats += ['', '## λ=1：来源分数描述', '', '| 追问臂 | 公式 | 数据集 | 身份 | n | 均值 | 来源SD |', '|---|---|---|---|---:|---:|---:|']
    for entry in report['operating_points_lambda1']:
        for group, values in entry['descriptive_scores'].items():
            stats.append(f"| {entry['arm']} | {entry['method']} | {entry['dataset']} | {group} | {values['n']} | {values['mean']:.6f} | {values['source_sd']:.6f} |")
    stats += ['', f"完整网格的逐库点估计、CI、配对增量、分数分布及所有 {report['selected_sources']} 篇的完整性信息在 `report.json`。", '']
    if secondary:
        stats += ['', '## 次要指标：配对区间与低FPR细节', '',
                  '次要指标沿用完整四方法得分向量，在membership层内按原来源数做配对bootstrap。95%区间为逐点分位区间，非同时区间；不新增p值或事后筛选。无预测正类时precision按0处理，MCC/NPV等零分母也采用0约定。', '',
                  'AP = Σ(该分数层成员数 / 全部成员数) × 累计precision；等分数一起处理，与sklearn非插值Average Precision一致。样本分数离散，未假设平滑PR曲线。', '',
                  '| 追问臂 | 指标 | 旧 [95% CI] | 新 [95% CI] | 新−旧 [95% CI] |', '|---|---|---|---|---|']
        lookup = {(entry['dataset'], entry['arm'], entry['method']): entry for entry in secondary['entries']}
        for delta in secondary['contrasts']:
            key = delta['dataset'], delta['arm']
            old, new = (lookup[(*key, method)]['metrics'][delta['metric']] for method in ('old', 'new'))
            stats.append(f"| {delta['arm']} | {delta['metric']} | {old['estimate']:.6f} {ci(old['ci95'])} | {new['estimate']:.6f} {ci(new['ci95'])} | {delta['delta']:+.6f} {ci(delta['ci95'])} |")
        stats += ['', '| 追问臂 | 公式 | FPR上限 | 阈值 | TP / FP | TPR [95% CP] | 实际FPR [95% CP] |',
                  '|---|---|---:|---:|---|---|---|']
        for entry in secondary['entries']:
            for point in entry['low_fpr']:
                stats.append(f"| {entry['arm']} | {entry['method']} | {point['target_fpr']:.4f} | {point['threshold']} | {point['true_positive_count']} / {point['false_positive_count']} | {point['TPR']:.6f} {ci(point['TPR_CI95_conditional_on_threshold'])} | {point['achieved_FPR']:.6f} {ci(point['FPR_CI95_conditional_on_threshold'])} |")
        stats += ['', 'CP区间条件于展示阈值，不校正事后ROC点选择；零经验误报不保证总体FPR=0。Balanced accuracy仅在成员/非成员等数时与Accuracy相等。', '']
    (output / 'stats-appendix.md').write_text('\n'.join(stats), encoding='utf-8')
    catalog = ['# 图目录', '',
               f'- `figures/formula_comparison.png` / `.pdf`：主要比较图。完整来源使用{label_description}；上排{metric_name} AUC，下排新−旧AUC百分点。误差线为来源分层配对bootstrap的逐点95%区间。图注须含来源数、单次历史运行、固定λ网格及{scope}。先核对λ=1方向与区间，再比较其他权重；区间不是同时置信带。用于评估拒答扣分候选，不能证明独立测试改进。', '',
               '- `figures/coverage_and_refusals.png` / `.pdf`：支持图。数据为本批全部来源；左图按dataset×membership区分原完整来源、补问后完整来源和仍缺失来源，右图显示三槽初问答对/其他0分/拒答比例，无误差线。图注须说明分母分别为source数与3×source数、M/N含义及右图仅描述。观察拒答信号来自何处，以及来源覆盖是否完整；若有缺失须结合界限解释。', '',
               f'两图均无跨seed误差估计。本次属于{scope}，不是未见source验收。准确数值以同目录JSON和Markdown表为准。', '']
    (output / 'figure-catalog.md').write_text('\n'.join(catalog), encoding='utf-8')


def json_finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return 'Infinity' if value > 0 else ('-Infinity' if value < 0 else 'NaN')
    if isinstance(value, dict):
        return {key: json_finite(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_finite(item) for item in value]
    return value


def main_signed_formal() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.utils.hash import sha256_file

    parser = argparse.ArgumentParser(description='已完成正式数据的三值评分事后诊断；不校准、不调用模型')
    parser.add_argument('--signed-formal', action='store_true', required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--dataset', choices=('nfcorpus', 'scidocs', 'trec-covid'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--lambdas', type=float, nargs='+', default=list(SIGNED_LAMBDAS))
    parser.add_argument('--bootstrap', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=20261009)
    args = parser.parse_args()
    lambdas = validate_signed_lambdas(args.lambdas)
    if 0.0 not in lambdas or 1.0 not in lambdas:
        parser.error('grid_requires_lambda_zero_and_primary_lambda_one')
    if args.output.exists():
        raise FileExistsError(f'analysis_output_already_exists:{args.output}')
    features, metadata, hashes = load_signed_formal(args.input, args.dataset)
    grid = paired_signed_grid(features, lambdas, args.bootstrap, args.seed)
    for entry in grid:
        if entry['lambda'] not in (0.0, 1.0):
            continue
        method = 'local_only' if entry['lambda'] == 0.0 else entry['arm']
        if not math.isclose(entry['per_dataset'][args.dataset]['old']['auc'],
                            metadata['original_metrics'][method]['auc']['estimate'], abs_tol=1e-12):
            raise ValueError('original_report_auc_not_reproduced')
    nli = metadata['correctness_matcher'] == 'binary_target_rules_nli_v3'
    uncertain = sum(row['count'] for row in metadata['label_counts'] if row.get('review_status') == 'uncertain')
    negations = sum(row['count'] for row in metadata['label_counts']
                    if row['automatic_reason'] == 'negation_before_answer_not_aligned_with_question' and row['signed_outcome'] == 0)
    label_limits = ([
        '只复用已保存的NLI v3二值判定及refused理由；新旧公式共用标签，未重跑判分器，未混入旧Assistant修正。nfcorpus使用的判分版本不同，不合并为跨库主macro。',
        'v3是在响应可见后接入，原1%错误目标未通过，且没有新的独立人工验收；三值分类仍可能有系统性误差，source区间不覆盖这类误差。',
        '0分代表有效回答未被确认为正确且未标记拒答，不等于全部经人工确证答错。旧分数由固定v3标签重建；是否已有完整旧报告见metadata。',
    ] if nli else [
        '保持原canonical_surface_v3匹配器及已接入的Assistant逐回答修正，不重新运行NLI v3；因此与前一轮64篇开发对照的判分器不同，两批结果不能合并。',
        f'拒答是原规则理由的操作定义，仍可能漏检或误检；{uncertain}条未决语义争议与{negations}条否定冲突保留0，0分不等于全部已确认答错。区间不包含系统性判分误差。',
        '已有逐回答修正来自Assistant post-response annotation，不是独立人工盲审；追问仍有历史争议和未经逐项审阅的回答。',
    ])
    report = {
        'status': 'posthoc_formal_score_diagnostic', 'statistical_unit': 'source_document',
        'analysis_population': 'entire_completed_formal_dataset_cell', 'used_for_calibration': False,
        'formula_old': 'C + lambda * R', 'formula_new': '(C - U) + lambda * (R - V)',
        'normalized': False, 'primary_lambda': 1.0, 'selected_lambda_for_formal': None, 'lambda_grid': lambdas,
        'bootstrap_replicates': args.bootstrap, 'bootstrap_seed': args.seed, 'confidence': 0.95,
        'selected_sources': len(features), 'complete_sources': len(features), 'metadata': metadata,
        'coverage': signed_coverage(features), 'complete_case_grid': grid,
        'all_source_initial_grid': [entry for entry in grid if entry['lambda'] == 0.0],
        'operating_points_lambda1': signed_operating_points(features), 'input_hashes': hashes,
        'secondary_metrics_lambda1': signed_secondary_metrics(features, args.bootstrap, args.seed),
        'code': {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                 'analysis_script_sha256': sha256_file(Path(__file__)), 'metrics_sha256': sha256_file(ROOT / 'src/evaluation/metrics.py'),
                 'source_scoring_sha256': sha256_file(ROOT / 'src/evaluation/source_scoring.py'),
                 'uncommitted_analysis_code': True},
        'environment': {'python': sys.version, 'executable': sys.executable, 'numpy': np.__version__, 'matplotlib': matplotlib.__version__},
        'new_calls': {'victim': 0, 'api': 0, 'retriever': 0, 'nli_input_pairs': 0, 'nli_forward_batches': 0},
        'limitations': [
            '本批属于已经产生正式结果的来源；本次是新公式的事后诊断，不能称为开发校准或未见测试，也不据此选择最佳λ、改正式阈值或覆盖历史报告。',
            *label_limits,
            '仅本次指定的数据集、单一Generator×Retriever及固定seed；不生成跨库主macro，也不将两个追问臂当独立实验。',
            'source bootstrap假设每个membership层内来源可交换；不覆盖同主题近重复相关性、模型/index/seed变化及跨数据集泛化。',
            '低FPR操作点来自本批经验ROC、未插值；其观察FPR与条件二项区间不等于独立校准后的总体FPR保证。',
            '响应model ID一致，但没有system fingerprint时无法独立核验服务权重是否随时间漂移；本次没有新增模型或victim调用。',
        ],
        'reproduction_command': '& ' + "'" + sys.executable + "' -X utf8 -B " + ' '.join('"' + value + '"' for value in sys.argv),
    }
    if any(sha256_file(Path(path)) != expected for path, expected in hashes.items()):
        raise RuntimeError('analysis_input_changed_during_run')
    report['inputs_unchanged_after_analysis'] = True
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'source_features.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in features), encoding='utf-8')
    report['source_features_sha256'] = sha256_file(args.output / 'source_features.jsonl')
    secondary = report['secondary_metrics_lambda1']
    secondary.update(status=report['status'], source_features_sha256=report['source_features_sha256'],
                     analysis_script_sha256=report['code']['analysis_script_sha256'])
    write_json(args.output / 'other_metrics_lambda1.json', json_finite(secondary))
    signed_figures(args.output, report)
    signed_markdown(args.output, report)
    (args.output / 'report.json').write_text(json.dumps(json_finite(report), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'sources': len(features),
                      'primary_lambda_one': [row for row in grid if row['lambda'] == 1.0],
                      'operating_points_lambda1': report['operating_points_lambda1']}, ensure_ascii=False, indent=2))


def main_signed_development() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.utils.hash import sha256_file

    parser = argparse.ArgumentParser(description='只复用已保存判定的来源级三值评分开发诊断')
    parser.add_argument('--signed-development', action='store_true', required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--judgment-inputs', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--formal-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--lambdas', type=float, nargs='+', default=list(SIGNED_LAMBDAS))
    parser.add_argument('--bootstrap', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=20261009)
    parser.add_argument('--backfill-dir', type=Path)
    parser.add_argument('--run-missing', action='store_true', help='显式发起已授权的单库缺失追问')
    parser.add_argument('--dataset', choices=('nfcorpus', 'scidocs', 'trec-covid'))
    parser.add_argument('--max-new', type=int, default=0)
    args = parser.parse_args()
    lambdas = validate_signed_lambdas(args.lambdas)
    if 0.0 not in lambdas or 1.0 not in lambdas:
        parser.error('grid_requires_lambda_zero_and_primary_lambda_one')
    if args.run_missing:
        if args.backfill_dir is None or args.dataset is None or args.max_new < 1:
            parser.error('run_missing_requires_backfill_dir_dataset_and_max_new')
        features, _, hashes = load_signed_development(args.input, args.judgment_inputs, args.predictions, args.formal_manifest)
        result = run_missing_development(args.input, args.predictions, features, args.backfill_dir, args.dataset, args.max_new)
        if any(sha256_file(Path(path)) != expected for path, expected in hashes.items()):
            raise RuntimeError('original_input_changed_during_backfill')
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.output.exists():
        raise FileExistsError(f'analysis_output_already_exists:{args.output}')
    features, metadata, hashes = load_signed_development(args.input, args.judgment_inputs, args.predictions, args.formal_manifest, args.backfill_dir)
    complete = [row for row in features if row['complete']]
    backfill = metadata['backfill']
    superseded_statistics = backfill.get('superseded_prediction_attempt', {}).get('model_statistics', {})
    missing_sources = [row for row in features if not row['complete']]
    report = {
        'status': 'development_only_diagnostic', 'statistical_unit': 'source_document',
        'formula_old': 'C + lambda * R', 'formula_new': '(C - U) + lambda * (R - V)',
        'normalized': False, 'primary_lambda': 1.0, 'selected_lambda_for_formal': None, 'lambda_grid': lambdas,
        'bootstrap_replicates': args.bootstrap, 'bootstrap_seed': args.seed, 'confidence': 0.95,
        'selected_sources': len(features), 'complete_sources': len(complete), 'metadata': metadata,
        'coverage': signed_coverage(features),
        'complete_case_grid': paired_signed_grid(complete, lambdas, args.bootstrap, args.seed),
        'all_source_bounds': signed_auc_bounds(features, lambdas),
        'all_source_initial_grid': paired_signed_grid(features, [0.0], args.bootstrap, args.seed),
        'operating_points_lambda1': signed_operating_points(complete),
        'input_hashes': hashes,
        'code': {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                 'analysis_script_sha256': sha256_file(Path(__file__)), 'metrics_sha256': sha256_file(ROOT / 'src/evaluation/metrics.py'),
                 'source_scoring_sha256': sha256_file(ROOT / 'src/evaluation/source_scoring.py'),
                 'uncommitted_analysis_code': True},
        'environment': {'python': sys.version, 'executable': sys.executable, 'numpy': np.__version__, 'matplotlib': matplotlib.__version__},
        'new_calls': {'victim': backfill['response_records'], 'api': backfill['response_records'], 'retriever': 0,
                      'nli_input_pairs': backfill['model_statistics'].get('pairs', 0) + superseded_statistics.get('pairs', 0),
                      'nli_forward_batches': backfill['model_statistics'].get('forward_batches', 0) + superseded_statistics.get('forward_batches', 0)},
        'limitations': [
            f"历史门控与v3门控差异原使{len(features) - backfill['original_complete_sources']}篇来源缺{backfill['original_missing_followups']}条追问；本次补{backfill['response_records']}条。当前仍缺失{len(missing_sources)}篇来源；缺失不能补零或假设随机缺失。若全部补齐，识别界限退化为精确点值。",
            '已有v3判分开发材料是曾见的选择子集；本次没有依据新AUC选择source，但不代表全体原始cohort或新独立开发/测试集。',
            '旧公式也使用相同v3标签与门控重算，与历史旧matcher的原报告不是同一比较；本次只隔离公式效应。',
            '答错与拒答的区分依赖固定自动判分器，未做新的三分类独立人工盲审；CI不包含系统性判分误差。',
            '来源与正式6000篇source_key及跨字段文本hash零重叠；未读取正式response或指标。但本项目已有正式结果可见，本次只能作为后续候选诊断，不能追溯替换旧正式评分或宣称全程事前设计。',
            '每库Non-member样本少，低FPR结果只反映当前经验ROC的分辨率；0次误报不保证总体FPR≤1%。',
            '仅一次固定Generator×Retriever开发运行；source bootstrap不代表不同模型、索引或随机seed的稳定性。provider model ID一致，但响应没有system fingerprint，未独立核验服务指纹。',
            '补问发生在后续日期，保持原查询、原检索上下文、模板与解码参数，并核验返回model ID；缺少服务权重指纹时，不能完全排除时间漂移。补问不是新的独立source验收。',
        ],
        'reproduction_command': '& ' + "'" + sys.executable + "' -X utf8 -B " + ' '.join('"' + value + '"' for value in sys.argv),
    }
    if any(sha256_file(Path(path)) != expected for path, expected in hashes.items()):
        raise RuntimeError('analysis_input_changed_during_run')
    report['inputs_unchanged_after_analysis'] = True
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'source_features.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in features), encoding='utf-8')
    signed_figures(args.output, report)
    signed_markdown(args.output, report)
    (args.output / 'report.json').write_text(json.dumps(json_finite(report), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'selected_sources': len(features), 'complete_sources': len(complete),
                      'primary_lambda_one': [row for row in report['complete_case_grid'] if row['lambda'] == 1.0]}, ensure_ascii=False, indent=2))


def offline_source_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只读复核完整来源、三值计数和门控预算，不产生新的判分。"""
    from src.evaluation.source_scoring import source_scores

    scored = source_scores(rows, 1.0)
    identities: dict[str, str] = {}
    query_ids: set[str] = set()
    for row in scored:
        for field in ('source_hash', 'normalized_text_hash'):
            value = row.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError('missing_offline_source_identity')
            if value in identities and identities[value] != row['source_key']:
                raise ValueError('duplicate_offline_source_identity')
            identities[value] = row['source_key']
        ids = row['initial_query_ids'] + [qid for arm in SIGNED_ARMS for qid in row['arms'][arm]['gated_query_ids']]
        if len(set(ids)) != len(ids) or query_ids.intersection(ids):
            raise ValueError('duplicate_offline_query_identity')
        query_ids.update(ids)
    return sorted(scored, key=lambda row: row['source_key'])


def offline_binomial_rate(successes: int, total: int) -> dict[str, Any]:
    from scipy.stats import beta

    if not 0 <= successes <= total:
        raise ValueError('invalid_binomial_counts')
    return {'numerator': successes, 'denominator': total,
            'estimate': successes / total if total else None,
            'ci95': ([0.0 if successes == 0 else float(beta.ppf(0.025, successes, total - successes + 1)),
                      1.0 if successes == total else float(beta.ppf(0.975, successes + 1, total - successes))]
                     if total else None), 'interval': 'clopper_pearson_conditional_on_denominator'}


def offline_paired_metrics(
    rows: list[dict[str, Any]], columns: dict[str, list[float]], replicates: int, seed: int,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """同一来源的完整分数向量一起抽样；经验低FPR点在每次重抽中重选。"""
    from src.evaluation.metrics import roc_auc, rates_at_threshold, threshold_curve, tpr_at_fpr_details
    from sklearn.metrics import average_precision_score

    if replicates < 2 or not rows or len({row['dataset'] for row in rows}) != 1:
        raise ValueError('single_dataset_paired_bootstrap_required')
    if len({row['source_key'] for row in rows}) != len(rows):
        raise ValueError('duplicate_offline_source_sample')
    if any(len(values) != len(rows) for values in columns.values()):
        raise ValueError('source_score_vector_length_mismatch')
    matrix = np.asarray(list(columns.values()), dtype=float).T
    if not np.isfinite(matrix).all():
        raise ValueError('nonfinite_offline_score')
    if set(row['group'] for row in rows) != set(SIGNED_GROUPS):
        raise ValueError('both_membership_groups_required')
    positive, negative = (matrix[[row['group'] == group for row in rows]] for group in SIGNED_GROUPS)
    m, n = len(positive), len(negative)
    if min(m, n) < 2:
        raise ValueError('insufficient_sources_for_offline_bootstrap')
    positive, pc = np.unique(positive, axis=0, return_counts=True)
    negative, nc = np.unique(negative, axis=0, return_counts=True)
    rng = np.random.default_rng(seed)
    mw = np.vstack([pc, rng.multinomial(m, pc / m, size=replicates)])
    nw = np.vstack([nc, rng.multinomial(n, nc / n, size=replicates)])
    wins = (positive[:, None, :] > negative[None, :, :]).astype(float)
    wins += 0.5 * (positive[:, None, :] == negative[None, :, :])
    aucs = np.einsum('bi,ijk,bj->bk', mw, wins, nw, optimize=True) / (m * n)
    entries, draws = {}, {}
    labels = [row['group'] == SIGNED_GROUPS[0] for row in rows]
    for j, (name, values) in enumerate(columns.items()):
        scored = [dict(group=row['group'], score=float(value)) for row, value in zip(rows, values)]
        levels = np.unique(np.r_[positive[:, j], negative[:, j]])[::-1]
        ph = mw @ (positive[:, j, None] == levels)
        nh = nw @ (negative[:, j, None] == levels)
        tp, fp = ph.cumsum(axis=1), nh.cumsum(axis=1)
        precision = np.divide(tp, tp + fp, out=np.zeros_like(tp, dtype=float), where=tp + fp != 0)
        ap = np.sum(ph / m * precision, axis=1)
        if not math.isclose(float(aucs[0, j]), float(roc_auc(scored, 'score')), abs_tol=1e-12):
            raise AssertionError('offline_auc_crosscheck_failed')
        if not math.isclose(float(ap[0]), float(average_precision_score(labels, values)), abs_tol=1e-12):
            raise AssertionError('offline_ap_crosscheck_failed')
        fixed = rates_at_threshold(scored, 2.0, 'score')
        fixed['TPR_interval'] = offline_binomial_rate(fixed['true_positive_count'], m)
        fixed['FPR_interval'] = offline_binomial_rate(fixed['false_positive_count'], n)
        curve = threshold_curve(scored, 'score')
        low_fpr = []
        for target in (0.0, 0.001, 0.01, 0.05):
            point = tpr_at_fpr_details(curve, target)
            selected = next(item for item in curve if item['threshold'] == point['threshold'])
            point.update(true_positive_count=selected['true_positive_count'], positive_count=m)
            point['TPR_interval_conditional_on_selected_threshold'] = offline_binomial_rate(point['true_positive_count'], m)
            point['FPR_interval_conditional_on_selected_threshold'] = offline_binomial_rate(point['false_positive_count'], n)
            eligible = fp / n <= target + 1e-15
            # “全拒绝”的+inf点总是可达；只需给最大可达TPR的bootstrap分布。
            samples = np.max(np.where(eligible, tp / m, 0.0), axis=1)
            point['TPR_source_bootstrap_ci95_reselecting_roc_point'] = np.quantile(samples[1:], [0.025, 0.975]).tolist()
            if not math.isclose(float(samples[0]), point['TPR'], abs_tol=1e-12):
                raise AssertionError('offline_low_fpr_crosscheck_failed')
            draws[f'{name}/tpr_at_{target:g}'] = samples[1:]
            low_fpr.append(point)
        entries[name] = {'auc': {'estimate': float(aucs[0, j]), 'ci95': np.quantile(aucs[1:, j], [0.025, 0.975]).tolist()},
                         'average_precision': {'estimate': float(ap[0]), 'ci95': np.quantile(ap[1:], [0.025, 0.975]).tolist()},
                         'fixed_cutoff': fixed, 'low_fpr': low_fpr,
                         'score_descriptions': {group: {
                             'n': sum(row['group'] == group for row in rows),
                             'mean': float(np.mean([value for row, value in zip(rows, values) if row['group'] == group])),
                             'source_sd': float(np.std([value for row, value in zip(rows, values) if row['group'] == group], ddof=1)),
                             'distribution': dict(sorted(Counter(str(value) for row, value in zip(rows, values) if row['group'] == group).items())),
                         } for group in SIGNED_GROUPS}}
        draws[f'{name}/auc'] = aucs[1:, j]
    return entries, draws


def offline_components(rows: list[dict[str, Any]], replicates: int, seed: int) -> dict[str, Any]:
    columns = {'C': [row['initial_correct'] for row in rows],
               'minus_U': [-row['initial_refused'] for row in rows],
               'C_minus_U': [row['signed_initial'] for row in rows]}
    formulas = {'old': 'C + R', 'initial_penalty_only': 'C - U + R',
                'followup_penalty_only': 'C + R - V', 'full_new': 'C - U + R - V'}
    for arm in SIGNED_ARMS:
        for method in formulas:
            columns[f'{arm}/{method}'] = [
                row['initial_correct'] + row['arms'][arm]['correct']
                - (row['initial_refused'] if method in ('initial_penalty_only', 'full_new') else 0)
                - (row['arms'][arm]['refused'] if method in ('followup_penalty_only', 'full_new') else 0)
                for row in rows]
    entries, draws = offline_paired_metrics(rows, columns, replicates, seed)
    contrasts = []
    for arm in SIGNED_ARMS:
        for before, after in (('old', 'full_new'), ('old', 'initial_penalty_only'),
                              ('initial_penalty_only', 'full_new'), ('C_minus_U', 'full_new')):
            left, right = ('C_minus_U' if before == 'C_minus_U' else f'{arm}/{before}'), f'{arm}/{after}'
            for metric in ('auc', 'tpr_at_0.01', 'tpr_at_0.05'):
                def estimate(key: str) -> float:
                    if metric == 'auc':
                        return entries[key]['auc']['estimate']
                    return next(point['TPR'] for point in entries[key]['low_fpr'] if point['target_fpr'] == float(metric[7:]))
                delta = draws[f'{right}/{metric}'] - draws[f'{left}/{metric}']
                contrasts.append({'arm': arm, 'before': before, 'after': after, 'metric': metric,
                                  'delta': estimate(right) - estimate(left),
                                  'ci95': np.quantile(delta, [0.025, 0.975]).tolist()})
    return {'dataset': rows[0]['dataset'], 'lambda': 1.0, 'cutoff': 2.0, 'formulas': formulas,
            'entries': entries, 'paired_contrasts': contrasts, 'p_values_reported': False}


def offline_transitions(rows: list[dict[str, Any]], replicates: int, seed: int) -> list[dict[str, Any]]:
    from scipy.stats import binomtest

    rng = np.random.default_rng(seed)
    result = []
    for dataset in sorted({row['dataset'] for row in rows}):
        for group in SIGNED_GROUPS:
            subset = [row for row in rows if row['dataset'] == dataset and row['group'] == group]
            if len(subset) < 2 or replicates < 2:
                raise ValueError('insufficient_transition_bootstrap_sample')
            before = np.array([row['signed_initial'] >= 2 for row in subset], dtype=int)
            after = np.array([[row[arm] >= 2 for arm in SIGNED_ARMS] for row in subset], dtype=int)
            vectors, counts = np.unique(np.column_stack([before, after]), axis=0, return_counts=True)
            weights = rng.multinomial(len(subset), counts / len(subset), size=replicates)
            for j, arm in enumerate(SIGNED_ARMS, 1):
                cells = Counter((bool(row['signed_initial'] >= 2), bool(row[arm] >= 2)) for row in subset)
                n00, n01, n10, n11 = (cells[key] for key in ((False, False), (False, True), (True, False), (True, True)))
                n, bpos, apos = len(subset), n10 + n11, n01 + n11
                delta = weights @ (vectors[:, j] - vectors[:, 0]) / n
                entry = {'dataset': dataset, 'group': group, 'arm': arm, 'sources': n,
                         'initial_formula': 'C - U', 'after_formula': 'C - U + R - V', 'lambda': 1.0, 'cutoff': 2.0,
                         'cells': {'negative_negative': n00, 'negative_positive': n01,
                                   'positive_negative': n10, 'positive_positive': n11},
                         'positive_rate_before': offline_binomial_rate(bpos, n),
                         'positive_rate_after': offline_binomial_rate(apos, n),
                         'delta_positive_rate': (apos - bpos) / n,
                         'delta_positive_rate_ci95': np.quantile(delta, [0.025, 0.975]).tolist(),
                         'positive_retention': offline_binomial_rate(n11, bpos),
                         'positive_loss': offline_binomial_rate(n10, bpos),
                         'new_positive': offline_binomial_rate(n01, n - bpos)}
                if group == 'True_Non_Member':
                    entry['initial_false_positive_correction'] = entry['positive_loss']
                if arm == 'correct_anchor':
                    entry['paired_test'] = {'method': 'exact_two_sided_mcnemar_binomial',
                                            'discordant_sources': n10 + n01,
                                            'p_raw': float(binomtest(n10, n10 + n01, 0.5).pvalue) if n10 + n01 else 1.0}
                result.append(entry)
    tests = [entry['paired_test'] for entry in result if 'paired_test' in entry]
    running = 0.0
    for rank, test in enumerate(sorted(tests, key=lambda test: test['p_raw'])):
        running = max(running, min(1.0, (len(tests) - rank) * test['p_raw']))
        test.update(p_holm=running, family_size=len(tests), family='ReCheck_by_dataset_and_membership')
    return result


def offline_costs(rows: list[dict[str, Any]], replicates: int, seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    summary, strata, differences = [], [], []
    for dataset in sorted({row['dataset'] for row in rows}):
        mean_draws = {}
        for group in (*SIGNED_GROUPS, 'All'):
            subset = [row for row in rows if row['dataset'] == dataset and (group == 'All' or row['group'] == group)]
            if len(subset) < 2 or replicates < 2:
                raise ValueError('insufficient_cost_bootstrap_sample')
            counts = np.bincount([row['initial_correct'] for row in subset], minlength=4)
            samples = rng.multinomial(len(subset), counts / len(subset), size=replicates) @ np.arange(3, 7) / len(subset)
            # 全体均值也保持两个membership层的原始数量，不随机改变类别比例。
            if group == 'All':
                sizes = [sum(row['group'] == g for row in subset) for g in SIGNED_GROUPS]
                samples = sum(mean_draws[g] * size for g, size in zip(SIGNED_GROUPS, sizes)) / sum(sizes)
            else:
                mean_draws[group] = samples
            values = np.array([3 + row['initial_correct'] for row in subset])
            summary.append({'dataset': dataset, 'group': group, 'sources': len(subset),
                            'initial_calls': 3 * len(subset), 'main_followup_calls': int(sum(row['initial_correct'] for row in subset)),
                            'main_logical_calls': int(values.sum()), 'both_arms_logical_calls': int(sum(3 + 2 * row['initial_correct'] for row in subset)),
                            'mean': float(values.mean()), 'mean_ci95': np.quantile(samples, [0.025, 0.975]).tolist(),
                            'source_sd': float(values.std(ddof=1)), 'min': int(values.min()), 'max': int(values.max()),
                            'median': float(np.quantile(values, 0.5, method='inverted_cdf')),
                            'p90': float(np.quantile(values, 0.9, method='inverted_cdf')),
                            'p95': float(np.quantile(values, 0.95, method='inverted_cdf')),
                            'distribution': {str(k + 3): int(counts[k]) for k in range(4)}})
            if group == 'All':
                continue
            for k in range(4):
                part = [row for row in subset if row['initial_correct'] == k]
                entry = {'dataset': dataset, 'group': group, 'K': k, 'sources': len(part),
                         'membership_share': len(part) / len(subset), 'main_calls_per_source': 3 + k,
                         'both_arms_calls_per_source': 3 + 2 * k, 'arms': {}}
                for arm in SIGNED_ARMS:
                    counts_by_outcome = {field: sum(row['arms'][arm][field] for row in part) for field in ('correct', 'refused', 'wrong')}
                    values = [row[arm] for row in part]
                    rates = {field: {'estimate': count / (k * len(part)) if k and part else None, 'ci95': None}
                             for field, count in counts_by_outcome.items()}
                    if part and k:
                        types, freq = np.unique([[row['arms'][arm][field] for field in ('correct', 'refused', 'wrong')] for row in part], axis=0, return_counts=True)
                        draws = rng.multinomial(len(part), freq / len(part), size=replicates) @ types / (k * len(part))
                        for j, field in enumerate(rates):
                            rates[field]['ci95'] = np.quantile(draws[:, j], [0.025, 0.975]).tolist()
                    entry['arms'][arm] = {'followup_queries': k * len(part), 'outcome_counts': counts_by_outcome,
                                          'followup_rates_source_bootstrap': rates,
                                          'score_mean': float(np.mean(values)) if values else None,
                                          'source_score_sd': float(np.std(values, ddof=1)) if len(values) > 1 else None,
                                          'score_distribution': dict(sorted(Counter(str(value) for value in values).items()))}
                strata.append(entry)
        delta = mean_draws[SIGNED_GROUPS[0]] - mean_draws[SIGNED_GROUPS[1]]
        means = {entry['group']: entry['mean'] for entry in summary if entry['dataset'] == dataset}
        differences.append({'dataset': dataset, 'contrast': 'Member_minus_Nonmember_mean_main_queries',
                            'delta': means[SIGNED_GROUPS[0]] - means[SIGNED_GROUPS[1]],
                            'ci95': np.quantile(delta, [0.025, 0.975]).tolist()})
    return {'formula_main': '3 + K', 'formula_both_arms': '3 + 2*K', 'K': 'number_of_correct_initial_slots_in_three',
            'summary': summary, 'by_membership_and_K': strata, 'member_minus_nonmember': differences,
            'excluded_costs': ['retries_and_failed_client_attempts', 'offline_query_construction_and_review',
                               'NLI_inference', 'index_build', 'tokens', 'latency', 'money']}


def offline_a1_outputs(output: Path, report: dict[str, Any]) -> None:
    import csv

    def csv_table(name: str, records: list[dict[str, Any]]) -> None:
        with (output / name).open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)

    def ci(values: list[float] | None) -> str:
        return '未定义' if values is None else f'[{values[0]:.6f}, {values[1]:.6f}]'

    def rate(value: dict[str, Any]) -> str:
        return '未定义（分母0）' if value['estimate'] is None else f"{value['numerator']}/{value['denominator']} = {value['estimate']:.2%}"

    components = report['trec_components']['entries']
    csv_table('trec_components.csv', [dict(component=name, auc=value['auc']['estimate'], auc_ci_low=value['auc']['ci95'][0],
        auc_ci_high=value['auc']['ci95'][1], ap=value['average_precision']['estimate'],
        tpr_cutoff2=value['fixed_cutoff']['TPR'], fpr_cutoff2=value['fixed_cutoff']['FPR'],
        tpr_at_1pct=value['low_fpr'][2]['TPR'], selected_threshold_1pct=value['low_fpr'][2]['threshold'],
        achieved_fpr_1pct=value['low_fpr'][2]['achieved_FPR'], tpr_at_5pct=value['low_fpr'][3]['TPR']) for name, value in components.items()])
    csv_table('trec_lambda.csv', [dict(arm=entry['arm'], weight=entry['lambda'],
        old_auc=entry['per_dataset']['trec-covid']['old']['auc'], new_auc=entry['per_dataset']['trec-covid']['new']['auc'],
        delta_auc=entry['per_dataset']['trec-covid']['delta_auc'], delta_ci95=entry['per_dataset']['trec-covid']['delta_ci95'])
        for entry in report['trec_lambda_grid']])
    csv_table('source_transitions.csv', [dict(dataset=e['dataset'], membership=e['group'], arm=e['arm'],
        n=e['sources'], **e['cells'], positive_before=e['positive_rate_before']['numerator'],
        positive_after=e['positive_rate_after']['numerator'], delta_positive_rate=e['delta_positive_rate'],
        delta_ci95=e['delta_positive_rate_ci95'], conditional_positive_loss=e['positive_loss']['estimate'],
        conditional_positive_retention=e['positive_retention']['estimate'], conditional_new_positive=e['new_positive']['estimate'],
        p_raw=e.get('paired_test', {}).get('p_raw'), p_holm=e.get('paired_test', {}).get('p_holm')) for e in report['transitions']])
    csv_table('query_costs.csv', report['costs']['summary'])
    csv_table('membership_K.csv', [dict(dataset=e['dataset'], membership=e['group'], K=e['K'], n=e['sources'],
        membership_share=e['membership_share'], main_queries_per_source=e['main_calls_per_source'],
        followup_queries=e['arms']['correct_anchor']['followup_queries'],
        correct_rate=e['arms']['correct_anchor']['followup_rates_source_bootstrap']['correct']['estimate'],
        correct_ci95=e['arms']['correct_anchor']['followup_rates_source_bootstrap']['correct']['ci95'],
        refusal_rate=e['arms']['correct_anchor']['followup_rates_source_bootstrap']['refused']['estimate'],
        refusal_ci95=e['arms']['correct_anchor']['followup_rates_source_bootstrap']['refused']['ci95'],
        score_mean=e['arms']['correct_anchor']['score_mean'], score_distribution=e['arms']['correct_anchor']['score_distribution'])
        for e in report['costs']['by_membership_and_K']])

    figures = output / 'figures'
    figures.mkdir()
    def save(fig: Any, name: str) -> None:
        fig.savefig(figures / f'{name}.png', dpi=220, bbox_inches='tight')
        fig.savefig(figures / f'{name}.pdf', bbox_inches='tight')
        plt.close(fig)

    labels = ['C', '-U', 'C-U', 'C+R', 'C-U+R', 'C+R-V', 'C-U+R-V']
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), layout='constrained', sharey=True)
    for ax, arm, title in zip(axes, SIGNED_ARMS, ('ReCheck', 'Existing follow-up control')):
        keys = ['C', 'minus_U', 'C_minus_U', *[f'{arm}/{name}' for name in report['trec_components']['formulas']]]
        estimates = np.array([components[key]['auc']['estimate'] for key in keys])
        intervals = np.array([components[key]['auc']['ci95'] for key in keys]).T
        ax.errorbar(range(len(keys)), estimates, yerr=np.maximum(0, np.stack([estimates - intervals[0], intervals[1] - estimates])), fmt='o', capsize=4)
        ax.set(xticks=range(len(keys)), xticklabels=labels, ylim=(0.75, 1.005), title=title, ylabel='Source AUROC')
        ax.tick_params(axis='x', labelrotation=35)
        ax.grid(axis='y', alpha=.25)
    fig.suptitle('TREC-COVID components | lambda=1 | paired source bootstrap 95% CI')
    save(fig, 'trec_components')
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.6), layout='constrained', sharey=True)
    for ax, arm, title in zip(axes, SIGNED_ARMS, ('ReCheck', 'Existing follow-up control')):
        grid = [entry for entry in report['trec_lambda_grid'] if entry['arm'] == arm]
        for method, label in (('old', 'C + lambda*R'), ('new', 'C-U + lambda*(R-V)')):
            x = [entry['lambda'] for entry in grid]
            y = np.array([entry['per_dataset']['trec-covid'][method]['auc'] for entry in grid])
            intervals = np.array([entry['per_dataset']['trec-covid'][method]['ci95'] for entry in grid]).T
            ax.errorbar(x, y, yerr=np.maximum(0, np.stack([y - intervals[0], intervals[1] - y])), marker='o', capsize=3, label=label)
        ax.axvline(1, color='gray', linestyle='--', linewidth=1)
        ax.set(title=title, xlabel='lambda (sensitivity only)', ylabel='Source AUROC')
        ax.grid(alpha=.25)
        ax.legend(fontsize=8)
    fig.suptitle('TREC-COVID fixed 7-point grid | lambda=1 retained')
    save(fig, 'trec_lambda')
    datasets = sorted(report['metadata'])
    fig, axes = plt.subplots(2, 3, figsize=(12, 7.4), layout='constrained')
    for j, dataset in enumerate(datasets):
        for i, group in enumerate(SIGNED_GROUPS):
            entry = next(e for e in report['transitions'] if (e['dataset'], e['group'], e['arm']) == (dataset, group, 'correct_anchor'))
            cells = entry['cells']
            counts = np.array([[cells['negative_negative'], cells['negative_positive']], [cells['positive_negative'], cells['positive_positive']]])
            ax = axes[i, j]
            ax.imshow(counts, cmap='Blues', vmin=0, vmax=1000)
            for (r, c), value in np.ndenumerate(counts):
                ax.text(c, r, f'{value}\n({value / entry["sources"]:.1%})', ha='center', va='center', color='white' if value > 500 else 'black')
            ax.set(xticks=[0, 1], xticklabels=['Negative', 'Positive'], yticks=[0, 1], yticklabels=['Negative', 'Positive'],
                   xlabel='After: ReCheck', ylabel='Before: C-U', title=f'{dataset} | {"Member" if i == 0 else "Nonmember"} (n={entry["sources"]})')
    fig.suptitle('Paired source transitions | lambda=1, cutoff=2 | each source counted once')
    save(fig, 'source_transitions')
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.6), layout='constrained', sharey=True)
    for ax, dataset in zip(axes, datasets):
        for shift, group, label in ((-.18, SIGNED_GROUPS[0], 'Member'), (.18, SIGNED_GROUPS[1], 'Nonmember')):
            e = next(e for e in report['costs']['summary'] if e['dataset'] == dataset and e['group'] == group)
            counts = np.array(list(e['distribution'].values()))
            bars = ax.bar(np.arange(3, 7) + shift, 100 * counts / e['sources'], width=.34, label=f'{label}: mean {e["mean"]:.3f}')
            for bar, count in zip(bars, counts):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1, str(count), ha='center', fontsize=8)
        ax.set(xticks=range(3, 7), title=dataset, xlabel='Main logical queries per source (3+K)', ylabel='Sources (%)', ylim=(0, 100))
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=.2)
    fig.suptitle('Query cost by membership | bar labels: source counts | n=1000 per group')
    save(fig, 'query_costs')

    lines = ['# ReCheck三项离线分析（A1）', '',
        '本次完成TREC-COVID评分组件与七点λ、三库固定阈值逐文档转移、成员/非成员及K分层查询成本。全部复用已保存回答和判分，新增victim/API/Retriever/NLI推理均为0。λ=1、阈值2保持；结果是已见来源上的事后诊断。', '',
        f'三库各2000篇来源，Member/Nonmember各1000；Gemma-2-2b-it-bf16、BGE-base-en-v1.5、k=5、128/32 tokens切块、历史seed=45。来源配对bootstrap{report["bootstrap_replicates"]}次，统计seed={report["bootstrap_seed"]}。不同判分版本逐库报告，不生成混合主macro。', '',
        '当前最清楚的收益是提高成员检出，同时保留绝大部分初问检出；固定阈值误报变化小且方向不一致。它支持继续验证正确性门控追问的检出收益与查询效率，还不足以把“稳定纠正误报”作为已证实的核心结论。', '',
        '## TREC-COVID组件与λ', '',
        '| 组件/追问臂 | AUROC [95% CI] | AP | 阈值2 TPR / FPR | 经验TPR@≤1%（实际FPR，阈值） |',
        '|---|---|---:|---|---|']
    for name, e in components.items():
        point = e['low_fpr'][2]
        lines.append(f'| {name} | {e["auc"]["estimate"]:.6f} {ci(e["auc"]["ci95"])} | {e["average_precision"]["estimate"]:.6f} | {e["fixed_cutoff"]["TPR"]:.2%} / {e["fixed_cutoff"]["FPR"]:.2%} | {point["TPR"]:.2%}（{point["achieved_FPR"]:.2%}，{point["threshold"]}） |')
    penalty = next(e for e in report['trec_components']['paired_contrasts']
                   if e['arm'] == 'correct_anchor' and e['before'] == 'initial_penalty_only' and e['metric'] == 'auc')
    initial_penalty = next(e for e in report['trec_components']['paired_contrasts']
                          if e['arm'] == 'correct_anchor' and e['before'] == 'old' and e['after'] == 'initial_penalty_only' and e['metric'] == 'auc')
    lines += ['', f'TREC主方法的新旧式AUROC为0.9809565与0.970254。初问拒答扣分−U在固定C+R上增加{initial_penalty["delta"]:.6f} AUC，配对CI {ci(initial_penalty["ci95"])}；追加追问拒答扣分−V仅增加{penalty["delta"]:.6f}，CI {ci(penalty["ci95"])}跨0。与已有两库相同，当前证据不能证明−V独立带来稳定AUC收益。', '',
        '−V也有操作点权衡：TREC的C−U+R在阈值2下TPR/FPR=89.8%/3.0%，全式为88.5%/2.0%；经验TPR@≤1%从81.3%到79.1%。保留这个不利结果，不据本批数据删除−V或修改阈值。']
    lines += ['', '代码字段correct_anchor表示ReCheck主方法，remote_only表示已有追问对照；字段沿用历史产物身份。C是初问正确数，U是初问拒答数，R/V是正确性门控内追问的正确/拒答数。其他有效回答计0。所有追问组件使用同一已保存查询和标签，不是重新构造攻击。', '',
        '| 臂 | λ | 旧式AUROC | 当前式AUROC [95% CI] | 当前−旧式 [配对95% CI] |', '|---|---:|---:|---|---|']
    for e in report['trec_lambda_grid']:
        v = e['per_dataset']['trec-covid']
        lines.append(f'| {e["arm"]} | {e["lambda"]:g} | {v["old"]["auc"]:.6f} | {v["new"]["auc"]:.6f} {ci(v["new"]["ci95"])} | {v["delta_auc"]:+.6f} {ci(v["delta_ci95"])} |')
    lines += ['', '固定λ=1的组件配对差值（含低FPR差值区间）见report.json；七点是敏感性分析，不选择最大值。初问组件只需3问，带追问组件的既定完整主预算为3+K；离线换公式和λ不产生额外请求。', '',
        '![TREC组件](figures/trec_components.png)', '', '![TREC λ敏感性](figures/trec_lambda.png)', '',
        '## 初问C−U → ReCheck：逐文档转移', '',
        '下面的初问比较使用当前评分的λ=0，即C−U；阈值均为2。非成员的“纠正”只在初问误报集合内定义，新增误报在原正确拒绝集合内定义。成员保留/损失在初问检出集合内定义，新增检出在初问漏检集合内定义。它与旧C+R→当前C−U+R−V的公式消融是两个不同问题。', '',
        '| 数据集 | 初问FP → 最终FP | 纠正初问误报 | 新增误报 | 初问TP → 最终TP | 保留初问检出 | 损失检出 | 新增检出 |',
        '|---|---|---|---|---|---|---|---|']
    for dataset in datasets:
        member, nonmember = (next(e for e in report['transitions'] if (e['dataset'], e['group'], e['arm']) == (dataset, group, 'correct_anchor')) for group in SIGNED_GROUPS)
        lines.append(f'| {dataset} | {nonmember["positive_rate_before"]["numerator"]} → {nonmember["positive_rate_after"]["numerator"]} | {rate(nonmember["positive_loss"])} | {rate(nonmember["new_positive"])} | {member["positive_rate_before"]["numerator"]} → {member["positive_rate_after"]["numerator"]} | {rate(member["positive_retention"])} | {rate(member["positive_loss"])} | {rate(member["new_positive"])} |')
    lines += ['', 'NF、SCIDOCS、TREC的成员检出分别净增133、152、113篇，即+13.3、+15.2、+11.3个百分点；初问检出保留率约98.4%、98.5%、98.8%。非成员分别纠正4/9、4/7、9/22篇初问误报，同时新增2、6、7篇误报；净误报为9→7、7→9、22→20。三库FPR差值CI均跨0，六项Holm校正后的非成员检验p均为1，不能据小分母声称稳定纠错。', '',
        '| 数据集 | C−U AUC → ReCheck AUC | ΔAUC [配对95% CI] | 经验TPR@≤1% 前 → 后 | ΔTPR@≤1% [配对95% CI] |', '|---|---|---|---|---|']
    for dataset in datasets:
        entries = report['initial_and_full_metrics'][dataset]
        effects = [e for e in report['initial_to_followup_contrasts'][dataset] if e['arm'] == 'correct_anchor']
        auc = next(e for e in effects if e['metric'] == 'auc')
        low = next(e for e in effects if e['metric'] == 'tpr_at_0.01')
        lines.append(f'| {dataset} | {entries["signed_initial"]["auc"]["estimate"]:.6f} → {entries["correct_anchor"]["auc"]["estimate"]:.6f} | {auc["delta"]:+.6f} {ci(auc["ci95"])} | {entries["signed_initial"]["low_fpr"][2]["TPR"]:.2%} → {entries["correct_anchor"]["low_fpr"][2]["TPR"]:.2%} | {low["delta"]:+.6f} {ci(low["ci95"])} |')
    lines += ['', '不把AUC增益等同于误报修正：若某库没有纠正误报，或新增误报更多，仍完整报告。已有追问对照的同口径转移也保存在JSON/CSV；对照与主方法共享来源，不作为第二批独立样本。', '',
        '![逐来源转移](figures/source_transitions.png)', '', '## 查询成本与K分层', '',
        'K为每篇三条初问中正确的槽位数；主方法3+K问，采集主方法与已有对照合计3+2K问，初问只计算一次。表内是成功逻辑查询数，不含失败尝试/重试、构造/审阅模型、NLI、索引构建，也不等同于token、延迟或货币成本。', '',
        '| 数据集 | 身份 | n | 主请求总数 | 均问数 [95% CI] | 中位/P90/P95 | 3/4/5/6问人数 |', '|---|---|---:|---:|---|---|---|']
    for e in report['costs']['summary']:
        lines.append(f'| {e["dataset"]} | {e["group"]} | {e["sources"]} | {e["main_logical_calls"]} | {e["mean"]:.4f} {ci(e["mean_ci95"])} | {e["median"]:g}/{e["p90"]:g}/{e["p95"]:g} | {"/".join(str(v) for v in e["distribution"].values())} |')
    lines += ['', '| 数据集 | 身份 | K | source数 | 追问数 | 追问正确率 | 追问拒答率 | 均问数 | 主分均值 |', '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for e in report['costs']['by_membership_and_K']:
        a = e['arms']['correct_anchor']
        def percent(v: float | None) -> str:
            return '未定义' if v is None else f'{v:.2%}'
        score = '未定义' if a['score_mean'] is None else f'{a["score_mean"]:.4f}'
        lines.append(f'| {e["dataset"]} | {e["group"]} | {e["K"]} | {e["sources"]} | {a["followup_queries"]} | {percent(a["followup_rates_source_bootstrap"]["correct"]["estimate"])} | {percent(a["followup_rates_source_bootstrap"]["refused"]["estimate"])} | {e["main_calls_per_source"]} | {score} |')
    lines += ['', 'K=0没有追问，追问比例记为未定义；来源仍保留在主分析与成本分母中。各K层的分数分布、来源SD及来源bootstrap追问率区间见report.json。槽位比例仅描述，区间按整篇source抽样。', '',
        f'三库主方法合计{report["main_logical_calls_total"]}次成功逻辑请求；两臂采集合计{report["both_arms_logical_calls_total"]}次。本次分析新增调用0，以上数字来自历史采集。', '',
        '成本高度依赖membership：成员平均5.102/5.232/5.300问，非成员3.073/3.127/3.205问；非成员中93.8%/88.3%/83.1%不触发追问。全体4.0875/4.1795/4.2525问来自1:1基准采样，不能直接当不同成员先验下的平均成本。相对于对全部来源发送三次追问的名义6问，当前成本更低；这只证明计数节省，是否性能更优仍需计划中的同预算/选槽对照。', '',
        '![成本分布](figures/query_costs.png)', '', '## 结论边界与复现', '',
        'NF使用canonical_surface_v3及已保存Assistant修正；SCIDOCS/TREC使用规则＋NLI v3。没有新的独立人工盲审，NLI的原1%接受目标未通过。CI条件于现有标签，不包含判分偏差；不能宣称已通过独立测试、跨模型泛化或正式release。单模型单运行的来源区间不代表多seed波动。', '',
        '经验低FPR阈值从本批ROC取得，不能当部署校准；1000非成员的最小非零FPR步长为0.1%。TREC阈值2下FPR仍为2%，与经验TPR@≤1%的阈值3分开报告。不根据此处结果更改参数。', '',
        '本次输入完整性、已有来源分数复算、AUC/AP独立实现核对及分析前后hash一致性均见report.json；原配置、判分、split、回答和历史评分报告保持。既有两库组件/λ证据链接见stats-appendix.md。', '',
        '```powershell', report['reproduction_command'], '```', '',
        '复现时指定新的空输出目录；本入口拒绝覆盖已有结果。精确数值、条件区间、检验定义和图注分别在report.json、stats-appendix.md、figure-catalog.md及五份CSV。']
    (output / 'analysis-report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    stats = ['# A1统计附录', '',
        '分析单位为source document。所有输入2000篇/库、身份各1000，初问三槽及当前gate内两臂完整；没有剔除K=0或低分来源。正文没有跨判分版本宏平均或跨库pool统计。', '',
        f'bootstrap={report["bootstrap_replicates"]}，seed={report["bootstrap_seed"]}。每库membership内按原人数有放回抽source，完整方法向量一起抽；类型合并的多项分布抽样与逐来源重抽等价。CI为逐点2.5%/97.5%分位区间，不是同时置信带。', '',
        'AUC并列计0.5；AP按召回增量加权precision、并列分数同时处理。两者分别与现有rank AUC和sklearn AP核对。固定阈值为score≥2；低FPR先最大TPR、再较小实际FPR、再较大阈值，不插值。低FPR bootstrap在每次重抽中重新选择可达ROC点，CP区间则条件于展示的原始阈值，不校正其选择。', '',
        '转移率的CP区间条件于相应初问子集；总体TPR/FPR差值用配对source bootstrap。只对ReCheck三库×两身份的六个before/after检验报告p：exact McNemar以两类不一致来源做双侧Binomial(n,0.5)，六项Holm校正。不为控制臂、K层或其他λ追加显著性筛选。这些是事后探索性检验，不能替代前瞻确认。', '',
        '成本均值在身份层内bootstrap；全体均值按原Member/Nonmember人数固定加权。来源SD是单次运行中来源差异，非运行SD。中位/P90/P95用inverted_cdf，返回实际观测整数。K层追问率是槽位计数比例，但区间抽整篇source；同一source共享追问目标的槽位不作为独立观察。', '',
        '| 数据集 | 身份 | 正类率前 → 后 [各自95% CP] | Δ正类率 [配对95% CI] | discordant n | exact p | Holm p（6项） |', '|---|---|---|---|---:|---:|---:|']
    for e in report['transitions']:
        if 'paired_test' not in e:
            continue
        test = e['paired_test']
        stats.append(f'| {e["dataset"]} | {e["group"]} | {e["positive_rate_before"]["estimate"]:.6f} {ci(e["positive_rate_before"]["ci95"])} → {e["positive_rate_after"]["estimate"]:.6f} {ci(e["positive_rate_after"]["ci95"])} | {e["delta_positive_rate"]:+.6f} {ci(e["delta_positive_rate_ci95"])} | {test["discordant_sources"]} | {test["p_raw"]:.8g} | {test["p_holm"]:.8g} |')
    stats += ['', '| 数据集 | 身份 | 主方法保留率CI | 损失/纠正率CI | 新增正类率CI |', '|---|---|---|---|---|']
    for e in report['transitions']:
        if e['arm'] == 'correct_anchor':
            stats.append(f'| {e["dataset"]} | {e["group"]} | {ci(e["positive_retention"]["ci95"])} | {ci(e["positive_loss"]["ci95"])} | {ci(e["new_positive"]["ci95"])} |')
    stats += ['', '## TREC固定λ=1的组件配对效应', '', '| 臂 | 组件前 → 后 | 指标 | Δ [95% CI] |', '|---|---|---|---|']
    for e in report['trec_components']['paired_contrasts']:
        stats.append(f'| {e["arm"]} | {e["before"]} → {e["after"]} | {e["metric"]} | {e["delta"]:+.6f} {ci(e["ci95"])} |')
    stats += ['', '## 原有两库证据', '']
    for dataset, item in report['prior_diagnostics'].items():
        stats.append(f'- [{dataset}已有诊断]({Path(item["directory"]).as_posix()}/analysis-report.md)：report及formula_component_review输入hash保存在本报告，未覆盖。')
    stats += ['', 'TREC λ=1的新−旧AUC近似中心化bootstrap p沿用原七点诊断实现，两个既有臂Holm校正，保存在trec_lambda_grid.primary_test。该检验属于单库原有公式诊断，与上述六项转移检验是不同问题；不把七点当七次确认性检验。', '',
        '来源在每库×身份层内可交换是推断假设；CI/p不覆盖主题近重复、人工/自动判分偏差、已见test后的方法选择、模型权重漂移、其他Generator/Retriever或跨seed。未进行正态性/方差齐性检验，因为采用非参数来源重抽/配对二项检验。', '',
        '新调用全0；逻辑请求数不含客户端失败尝试。当前配置和评分语义未改，不创建新的实验协议版本、不重跑victim、不将此分析升级为正式验收。']
    (output / 'stats-appendix.md').write_text('\n'.join(stats) + '\n', encoding='utf-8')
    catalog = ['# A1图目录', '',
        '| 图（PNG＋PDF） | 图注要点及读法 |', '|---|---|',
        '| trec_components | TREC各1000 Member/Nonmember、λ=1、单运行已见source；AUC点及配对来源bootstrap逐点95% CI。初问与两臂同源，不能把重合区间当独立检验。配对效应见JSON；评估组件作用，不据此改公式。 |',
        '| trec_lambda | 固定七点λ={0,0.25,0.5,1,1.5,2,4}；同source下新旧式AUC及逐点95% CI。竖线λ=1维持，不挑最高点；两个面板是既有主方法/控制臂。 |',
        '| source_transitions | 三库每身份1000 source；固定λ=1、阈值2。横轴追问后、纵轴初问C−U，单元格是source数及该身份占比，无误差线。右上新增正类，左下失去正类；Nonmember的失去正类是纠正误报，Member则是检出损失。 |',
        '| query_costs | 每库Member/Nonmember各1000；柱高身份内source比例，标数为原始人数。3+K为主方法成功逻辑查询；两臂及失败重试另计。无槽位独立误差线；均值来源CI见表。 |', '',
        '这些图是单模型单seed事后诊断，不证明独立来源泛化或跨模型稳定性。完整数值表为trec_components.csv、trec_lambda.csv、source_transitions.csv、query_costs.csv、membership_K.csv；逐source输入为source_features.jsonl。']
    (output / 'figure-catalog.md').write_text('\n'.join(catalog) + '\n', encoding='utf-8')


def main_offline_a1() -> None:
    from importlib.metadata import version
    from src.evaluation.source_scoring import load_scoring_config
    from src.utils.hash import sha256_file

    parser = argparse.ArgumentParser(description='ReCheck A1三项离线source统计；只读现有评分与固定输入')
    parser.add_argument('--offline-a1', action='store_true', required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--score-input', nargs=2, action='append', metavar=('DATASET', 'DIRECTORY'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bootstrap', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=20261009)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f'analysis_output_already_exists:{output}')
    if args.bootstrap < 2:
        parser.error('at_least_two_bootstrap_replicates_required')
    config = load_scoring_config(args.config.resolve())
    inputs = dict(args.score_input)
    if len(inputs) != len(args.score_input) or set(inputs) != {'nfcorpus', 'scidocs', 'trec-covid'}:
        parser.error('one_explicit_score_input_per_dataset_required')
    if config['scoring']['lambda'] != 1.0 or config['scoring']['operational_cutoff'] != 2.0:
        raise ValueError('offline_a1_requires_unchanged_lambda_one_cutoff_two')
    rows, metadata, hashes, prior = [], {}, {}, {}
    for dataset, directory in sorted(inputs.items()):
        root = Path(directory).resolve()
        if output.is_relative_to(root) or root.is_relative_to(output):
            raise ValueError('offline_output_overlaps_input')
        report_path, score_path = root / 'report.json', root / 'scores.jsonl'
        saved = read_json(report_path)
        if (saved.get('status') != 'mainline_scoring_complete' or saved.get('statistical_unit') != 'source_document'
                or saved.get('dataset') != dataset or saved.get('primary_arm') != 'correct_anchor'
                or saved.get('scoring') != config['scoring']
                or saved.get('code_sha256') != sha256_file(ROOT / 'src/evaluation/source_scoring.py')
                or sha256_file(score_path) != saved.get('scores_sha256')
                or Path(saved['metadata']['input_directory']).resolve() != (ROOT / config['inputs'][dataset]).resolve()):
            raise ValueError(f'offline_saved_score_binding_drift:{dataset}')
        for name, expected in saved['input_hashes'].items():
            path = Path(name).resolve()
            if sha256_file(path) != expected:
                raise ValueError(f'offline_saved_input_drift:{path.name}')
            hashes[str(path)] = expected
        raw = read_jsonl(score_path)
        scored = offline_source_rows(raw)
        by = {row['source_key']: row for row in scored}
        for row in raw:
            if any(row.get(name) != by[row['source_key']][name] for name in ('local_only', 'signed_initial', *SIGNED_ARMS)):
                raise ValueError('offline_saved_formula_drift')
        if (len(scored) != saved['source_count'] or dict(Counter(row['group'] for row in scored)) != saved['source_counts']
                or {row['dataset'] for row in scored} != {dataset}):
            raise ValueError('offline_saved_population_drift')
        n, k = len(scored), sum(row['initial_correct'] for row in scored)
        expected = {'initial': 3 * n, 'each_arm_including_initial': 3 * n + k, 'both_arms_including_initial': 3 * n + 2 * k}
        if any(saved['query_counts'][key] != value for key, value in expected.items()):
            raise ValueError('offline_saved_query_budget_drift')
        if saved['query_counts']['observed_responses'] != 3 * n + 2 * k:
            raise ValueError('historical_outside_gate_requires_separate_capture_cost')
        metadata[dataset] = {'historical_scoring_report': str(report_path), 'source_counts': saved['source_counts'],
                             'judge': saved['metadata']['correctness_matcher'], 'runtime': saved['metadata']['original_runtime'],
                             'evaluation_role': saved['evaluation_role'], 'formal_release_allowed': saved['formal_release_allowed'],
                             'query_counts': saved['query_counts'], 'original_seed': saved['seed']}
        hashes.update({str(report_path): sha256_file(report_path), str(score_path): sha256_file(score_path)})
        rows.extend(scored)
    rows = offline_source_rows(rows)
    for dataset in ('nfcorpus', 'scidocs'):
        directory = ROOT / f'artifacts/v25/diagnostics/signed_score_{dataset}_2000_20261009'
        prior[dataset] = {'directory': str(directory)}
        for name in ('report.json', 'formula_component_review.json'):
            path = directory / name
            digest = sha256_file(path)
            hashes[str(path)] = digest
            prior[dataset][name + '_sha256'] = digest
    hashes[str(args.config.resolve())] = sha256_file(args.config.resolve())
    trec = [row for row in rows if row['dataset'] == 'trec-covid']
    print('Computing TREC-COVID components and fixed lambda grid...', flush=True)
    components = offline_components(trec, args.bootstrap, args.seed)
    grid = paired_signed_grid(trec, list(SIGNED_LAMBDAS), args.bootstrap, args.seed)
    # 单库沿用原函数的内部均值字段，但不输出名为跨库macro的统计量。
    for entry in grid:
        entry.pop('macro')
        if 'primary_test' in entry:
            entry['primary_test']['null'] = 'trec_covid_delta_auc_equals_zero'
    print('Computing paired source transitions and membership/K query costs...', flush=True)
    transitions = offline_transitions(rows, args.bootstrap, args.seed)
    costs = offline_costs(rows, args.bootstrap, args.seed)
    metric_checks, initial_contrasts = {}, {}
    for dataset in sorted(metadata):
        subset = [row for row in rows if row['dataset'] == dataset]
        if dataset == 'trec-covid':
            entries = {'signed_initial': components['entries']['C_minus_U'],
                       **{arm: components['entries'][f'{arm}/full_new'] for arm in SIGNED_ARMS}}
            initial_contrasts[dataset] = [e for e in components['paired_contrasts'] if e['before'] == 'C_minus_U']
        else:
            entries, draws = offline_paired_metrics(subset, {name: [row[name] for row in subset] for name in ('signed_initial', *SIGNED_ARMS)}, args.bootstrap, args.seed)
            initial_contrasts[dataset] = []
            for arm in SIGNED_ARMS:
                for metric in ('auc', 'tpr_at_0.01', 'tpr_at_0.05'):
                    before = (entries['signed_initial']['auc']['estimate'] if metric == 'auc'
                              else next(p['TPR'] for p in entries['signed_initial']['low_fpr'] if p['target_fpr'] == float(metric[7:])))
                    after = (entries[arm]['auc']['estimate'] if metric == 'auc'
                             else next(p['TPR'] for p in entries[arm]['low_fpr'] if p['target_fpr'] == float(metric[7:])))
                    delta = draws[f'{arm}/{metric}'] - draws[f'signed_initial/{metric}']
                    initial_contrasts[dataset].append({'arm': arm, 'before': 'C_minus_U', 'after': 'full_new', 'metric': metric,
                                                       'delta': after - before, 'ci95': np.quantile(delta, [0.025, 0.975]).tolist()})
        old = read_json(Path(metadata[dataset]['historical_scoring_report']))
        if any(not math.isclose(entries[arm]['auc']['estimate'], old['metrics'][arm]['auc']['estimate'], abs_tol=1e-12) for arm in SIGNED_ARMS):
            raise AssertionError('historical_main_auc_not_reproduced')
        metric_checks[dataset] = entries
    report = {'status': 'posthoc_offline_a1_complete', 'statistical_unit': 'source_document',
              'primary_lambda': 1.0, 'operational_cutoff': 2.0, 'used_for_parameter_selection': False,
              'formal_release_allowed': False, 'mixed_judge_macro': None, 'source_count': len(rows),
              'bootstrap_replicates': args.bootstrap, 'bootstrap_seed': args.seed, 'confidence': .95,
              'metadata': metadata, 'trec_components': components, 'trec_lambda_grid': grid,
              'transitions': transitions, 'costs': costs, 'initial_and_full_metrics': metric_checks,
              'initial_to_followup_contrasts': initial_contrasts,
              'main_logical_calls_total': sum(e['main_logical_calls'] for e in costs['summary'] if e['group'] == 'All'),
              'both_arms_logical_calls_total': sum(e['both_arms_logical_calls'] for e in costs['summary'] if e['group'] == 'All'),
              'prior_diagnostics': prior, 'input_hashes': hashes,
              'code': {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                       'analysis_script_sha256': sha256_file(Path(__file__)), 'uncommitted_analysis_code': True},
              'environment': {'python': sys.version, 'executable': sys.executable, 'numpy': np.__version__, 'matplotlib': matplotlib.__version__,
                              'scipy': version('scipy'), 'sklearn': version('scikit-learn')},
              'new_calls': {'victim': 0, 'api': 0, 'retriever': 0, 'nli_input_pairs': 0, 'nli_forward_batches': 0},
              'reproduction_command': '& ' + "'" + sys.executable + "' -X utf8 -B " + ' '.join('"' + arg + '"' for arg in sys.argv)}
    if any(sha256_file(Path(name)) != digest for name, digest in hashes.items()):
        raise RuntimeError('offline_a1_input_changed_during_analysis')
    report['inputs_unchanged_after_analysis'] = True
    output.mkdir(parents=True, exist_ok=False)
    (output / 'source_features.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    report['source_features_sha256'] = sha256_file(output / 'source_features.jsonl')
    offline_a1_outputs(output, report)
    report['output_hashes'] = {str(path.relative_to(output)): sha256_file(path) for path in sorted(output.rglob('*')) if path.is_file()}
    (output / 'report.json').write_text(json.dumps(json_finite(report), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'sources': len(rows), 'main_logical_calls': report['main_logical_calls_total'],
                      'new_calls': report['new_calls'], 'status': report['status']}, ensure_ascii=False, indent=2))


CAPACITY_DATASETS = ('nfcorpus', 'scidocs', 'trec-covid')
CAPACITY_KEY_PATTERN = re.compile(r'\b(nfcorpus|scidocs|trec-covid)::([A-Za-z0-9_.-]+)')


def capacity_normalize(text: str) -> str:
    """严格沿用来源池的 v24._norm，不重新定义文本去重。"""
    return ' '.join(str(text or '').casefold().split())


def capacity_read_jsonl(path: Path):
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def capacity_identity_tokens(value: Any, dataset: str = '', field: str = '', reference: bool = False):
    """仅提取文档身份；旧标签、eligible、响应质量和分数不参与容量筛选。"""
    if isinstance(value, dict):
        dataset = str(value.get('dataset', dataset))
        for key, item in value.items():
            ref = reference or str(key).startswith(('excluded_', 'historical_', 'history_'))
            hint = str(key) if key in CAPACITY_DATASETS else dataset
            yield from capacity_identity_tokens(item, hint, str(key), ref)
    elif isinstance(value, list):
        for item in value:
            yield from capacity_identity_tokens(item, dataset, field, reference)
    elif isinstance(value, str):
        if field in ('source_key', 'source_id', 'document_id', 'doc_id') or field.endswith(('source_keys', 'member_keys', 'source_ids', 'document_ids', 'doc_ids')):
            matches = list(CAPACITY_KEY_PATTERN.finditer(value))
            if matches:
                for match in matches:
                    yield ('key', match.group(0), match.group(1), reference)
            elif dataset in CAPACITY_DATASETS:
                yield ('key', dataset + '::' + value, dataset, reference)
            elif '::' not in value:
                yield ('document_id', value, '', reference)
        elif field in ('source_hash', 'normalized_text_hash', 'source_text_sha256', 'full_text_sha256', 'text_sha256'):
            if re.fullmatch(r'[0-9a-f]{64}', value):
                yield ('hash', value, dataset, reference)
        elif field in ('full_text', 'source_text', 'text') and value:
            from src.utils.hash import sha256_text
            yield ('hash', sha256_text(value), dataset, reference)
            yield ('hash', sha256_text(capacity_normalize(value)), dataset, reference)


def capacity_file_category(path: Path, root: Path) -> str:
    """区分全池枚举、未执行准备、身份分配和实际构造/检索/判分记录。"""
    if 'source_pools' in path.relative_to(root).parts:
        return 'development_contact' if path.name == 'development_exclusions.json' else 'pool_catalogue'
    if path.name == 'candidate_manifest.jsonl':
        return 'candidate_catalogue'
    if path.suffix in ('.md', '.txt', '.zip'):
        return 'reference_only'
    if path.name in ('run_config.json', 'experiment_config.json', 'config.json') or path.name.endswith('.manifest.json'):
        return 'reference_only'
    if path.name in ('source_manifest.jsonl', 'index_manifest.jsonl', 'index_manifest.json'):
        run = path.parent
        files = {p.name for p in run.iterdir() if p.is_file()}
        if files <= {'run_config.json', 'source_manifest.jsonl', 'index_manifest.jsonl', 'index_manifest.json'} and 'run_config.json' in files:
            state = read_json(run / 'run_config.json').get('status')
            if state in ('prepared_before_construction', 'fixed_before_new_calls'):
                return 'preparation_only'
        if path.name.startswith('index_manifest') and any(
                run.joinpath(name).is_file() and run.joinpath(name).stat().st_size > 0
                for name in ('retrieval.jsonl', 'initial_responses.jsonl', 'responses.jsonl', 'index/chunks.jsonl')):
            return 'index_contact'
        return 'allocation_uncertain'
    if path.name in ('source_plan.json', 'source_split.json', 'split_manifest.json'):
        return 'allocation_uncertain'
    return 'operational_contact'


def capacity_load_pools(root: Path, dataset_configs: list[dict[str, Any]]):
    import sqlite3
    from src.utils.hash import sha256_file, sha256_obj, sha256_text
    sources, aliases, hashes, documents, pool_stats, inputs = {}, {}, defaultdict(set), defaultdict(set), {}, {}
    for config in dataset_configs:
        dataset = config['name']
        paths = config['source_pool']
        manifest_path, database_path, order_path = (root / paths[k] for k in ('manifest', 'database', 'source_order'))
        manifest = read_json(manifest_path)
        order = read_json(order_path)['source_order']
        corpus_path = Path(manifest['corpus_input_path'])
        if not corpus_path.is_absolute():
            corpus_path = root / corpus_path
        for path, expected in ((database_path, manifest['database_sha256']),
                               (order_path, manifest['source_order_sha256']),
                               (corpus_path, manifest['corpus_input_sha256'])):
            digest = sha256_file(path)
            if digest != expected:
                raise RuntimeError('capacity_pool_input_hash_drift:' + str(path))
            inputs[str(path.resolve())] = digest
        inputs[str(manifest_path.resolve())] = sha256_file(manifest_path)
        if sha256_obj(order) != manifest['source_order_content_sha256']:
            raise RuntimeError('capacity_source_order_content_drift:' + dataset)
        local, normalized = {}, {}
        connection = sqlite3.connect(database_path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            connection.execute('PRAGMA query_only=ON')
            for key, ds, doc, raw_hash, norm_hash, text, rows in connection.execute(
                    'SELECT source_key,dataset,document_id,source_hash,normalized_text_hash,full_text,input_row_count FROM sources'):
                if (ds != dataset or key != ds + '::' + doc or rows != 1 or key in local
                        or sha256_text(text) != raw_hash or sha256_text(capacity_normalize(text)) != norm_hash
                        or norm_hash in normalized):
                    raise RuntimeError('capacity_source_identity_drift:' + key)
                row = {'source_key': key, 'dataset': ds, 'document_id': doc, 'source_hash': raw_hash,
                       'normalized_text_hash': norm_hash, 'word_count': len(text.split())}
                local[key] = row
                normalized[norm_hash] = key
                sources[key] = row
                aliases[key] = key
                hashes[raw_hash].add(key)
                hashes[norm_hash].add(key)
                documents[doc].add(key)
        finally:
            connection.close()
        if len(order) != len(set(order)) or set(order) != set(local) or len(local) != manifest['frozen_source_count']:
            raise RuntimeError('capacity_source_order_identity_drift:' + dataset)
        counts = Counter()
        raw_ids, seen_norm = set(), set()
        for row in capacity_read_jsonl(corpus_path):
            doc = str(row['_id'])
            counts['raw_document_count'] += 1
            if doc in raw_ids:
                raise RuntimeError('capacity_corpus_duplicate_document_id:' + dataset)
            raw_ids.add(doc)
            text = (str(row.get('title') or '').strip() + '\n\n' + str(row.get('text') or '').strip()).strip()
            if not text:
                counts['empty_document_count'] += 1
                continue
            norm_hash = sha256_text(capacity_normalize(text))
            if norm_hash in seen_norm:
                counts['duplicate_text_count'] += 1
            seen_norm.add(norm_hash)
            if norm_hash not in normalized:
                raise RuntimeError('capacity_corpus_text_not_in_pool:' + dataset)
            canonical = normalized[norm_hash]
            if canonical == dataset + '::' + doc and sha256_text(text) != sources[canonical]['source_hash']:
                raise RuntimeError('capacity_corpus_document_raw_hash_drift:' + canonical)
            aliases[dataset + '::' + doc] = canonical
            hashes[sha256_text(text)].add(canonical)
            documents[doc].add(canonical)
        for field in ('raw_document_count', 'empty_document_count', 'duplicate_text_count'):
            if counts[field] != manifest[field]:
                raise RuntimeError('capacity_corpus_count_drift:' + dataset + ':' + field)
        pool_stats[dataset] = {**{field: int(manifest[field]) for field in
                                ('raw_document_count', 'empty_document_count', 'duplicate_text_count', 'frozen_source_count')},
                               'duplicate_document_id_count': 0, 'retained_raw_hash_errors': 0,
                               'retained_normalized_hash_errors': 0, 'source_order_identity_errors': 0,
                               'corpus_duplicate_alias_count': sum(key != value for key, value in aliases.items() if key.startswith(dataset + '::'))}
    return sources, aliases, hashes, documents, pool_stats, inputs


def capacity_resolve_token(token: tuple, aliases: dict, hashes: dict, documents: dict):
    kind, value, dataset, reference = token
    if kind == 'key':
        if value in aliases:
            return {aliases[value]}, False
        trimmed = value.rstrip('.')
        if trimmed in aliases:
            return {aliases[trimmed]}, False
        prefix = trimmed.split('::')[-1]
        if dataset == 'scidocs' and 5 <= len(prefix) < 40 and re.fullmatch('[0-9a-f]+', prefix):
            return {key for alias, key in aliases.items() if alias.startswith(dataset + '::' + prefix)}, True
        return set(), False
    if kind == 'hash':
        return set(hashes.get(value, set())), False
    matched = set(documents.get(value, set()))
    return matched, len(matched) > 1


def capacity_scan_history(root: Path, output: Path, sources: dict, aliases: dict, hashes: dict, documents: dict):
    import csv
    import os
    import zipfile
    from src.utils.hash import sha256_file
    files = set()
    for base in (root / 'artifacts', root / 'legacy', root / '研究记录'):
        for directory, dirs, names in os.walk(base):
            dirs[:] = [name for name in dirs if name not in ('.git', '__pycache__', 'models')
                       and not name.startswith('recheck_source_capacity_a2_') and Path(directory, name).resolve() != output]
            for name in names:
                path = Path(directory, name)
                if path.suffix.lower() in ('.json', '.jsonl', '.csv', '.md', '.txt', '.zip'):
                    files.add(path)
    files.update(path for path in root.iterdir() if path.is_file() and path.suffix in ('.md', '.txt'))
    events, inventory, unresolved, missing = defaultdict(lambda: defaultdict(set)), [], [], set()
    for index, path in enumerate(sorted(files)):
        category = capacity_file_category(path, root)
        record = {'file_id': index, 'path': str(path.relative_to(root)).replace('\\', '/'),
                  'bytes': path.stat().st_size, 'sha256': sha256_file(path), 'category': category,
                  'matched_source_count': 0, 'rows_read': 0, 'parse_error': ''}
        matched_file, missing_ids = set(), set()
        if category not in ('pool_catalogue', 'candidate_catalogue'):
            try:
                if path.suffix == '.jsonl':
                    values = capacity_read_jsonl(path)
                elif path.suffix == '.csv':
                    def csv_rows(filename):
                        with filename.open(encoding='utf-8-sig', newline='') as stream:
                            yield from csv.DictReader(stream)
                    values = csv_rows(path)
                elif path.suffix in ('.md', '.txt'):
                    text = path.read_text(encoding='utf-8-sig')
                    values = [{'source_key': match.group(0)} for match in CAPACITY_KEY_PATTERN.finditer(text)]
                    values += [{'document_id': match.group(0)} for match in re.finditer(r'\b(?:MED-\d+|[0-9a-f]{40}|[a-z0-9]{8})\b', text)
                               if match.group(0) in documents]
                elif path.suffix == '.zip':
                    with zipfile.ZipFile(path) as archive:
                        values = [json.loads(archive.read(name).decode('utf-8-sig')) for name in archive.namelist() if name.endswith('.json')]
                else:
                    values = [read_json(path)]
                hint = next((name for name in reversed(path.parts) if name in CAPACITY_DATASETS), '')
                for value in values:
                    record['rows_read'] += 1
                    for token in capacity_identity_tokens(value, hint):
                        matched, ambiguous = capacity_resolve_token(token, aliases, hashes, documents)
                        related = set(matched)
                        for key in matched:
                            related.update(hashes.get(sources[key]['source_hash'], set()))
                            related.update(hashes.get(sources[key]['normalized_text_hash'], set()))
                        matched = related
                        if not matched and token[0] == 'key' and token[2] in CAPACITY_DATASETS:
                            missing_ids.add(token[1])
                        event = 'allocation_uncertain' if ambiguous or token[3] else category
                        for key in matched:
                            events[key][event].add(index)
                        matched_file.update(matched)
                    if path.name in ('run_config.json', 'experiment_config.json') and isinstance(value, dict):
                        def input_paths(item):
                            if isinstance(item, dict):
                                for key, part in item.items():
                                    if isinstance(key, str) and key.replace('\\', '/').startswith(('artifacts/', 'datasets/', 'legacy/')):
                                        yield key
                                    yield from input_paths(part)
                            elif isinstance(item, list):
                                for part in item:
                                    yield from input_paths(part)
                        for name in input_paths(value):
                            if Path(name).suffix in ('.json', '.jsonl', '.csv', '.sqlite3') and not (root / name).exists():
                                missing.add((record['path'], name))
            except (ValueError, UnicodeError, OSError, zipfile.BadZipFile) as error:
                record['parse_error'] = type(error).__name__
        record['matched_source_count'] = len(matched_file)
        unresolved.extend({'file_id': index, 'source_key': key} for key in sorted(missing_ids))
        inventory.append(record)
    return events, inventory, unresolved, sorted(missing)


def capacity_classify_sources(sources: dict, events: dict, minimum_words: int):
    counts, rows, seen_hashes = {ds: Counter() for ds in CAPACITY_DATASETS}, [], set()
    used_categories = {'development_contact', 'index_contact', 'operational_contact'}
    for dataset in CAPACITY_DATASETS:
        for key in sorted(key for key, row in sources.items() if row['dataset'] == dataset):
            row = dict(sources[key])
            evidence = events.get(key, {})
            if used_categories.intersection(evidence):
                status = 'known_contact'
            elif set(evidence).intersection({'allocation_uncertain', 'reference_only'}):
                status = 'history_uncertain'
            elif row['word_count'] < minimum_words:
                status = 'below_minimum_words'
            elif {row['source_hash'], row['normalized_text_hash']}.intersection(seen_hashes):
                status = 'cross_dataset_duplicate'
            else:
                status = 'no_record_candidate'
                seen_hashes.update((row['source_hash'], row['normalized_text_hash']))
            counts[dataset][status] += 1
            if 'preparation_only' in evidence:
                counts[dataset]['preparation_only_any'] += 1
                if status == 'no_record_candidate':
                    counts[dataset]['preparation_only_candidate'] += 1
            row.update(status=status, evidence={name: sorted(ids) for name, ids in sorted(evidence.items())})
            rows.append(row)
    return rows, counts


def main_source_capacity() -> None:
    import csv
    from datetime import datetime, timezone
    from src.utils.hash import sha256_file
    from src.utils.io import load_yaml
    parser = argparse.ArgumentParser(description='A2来源容量与历史接触只读盘点；不分组，不调用模型')
    parser.add_argument('--audit-source-capacity', action='store_true', required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise RuntimeError('capacity_output_must_be_new_workspace_directory')
    config = load_yaml(args.config)
    dataset_names = [row['name'] if isinstance(row, dict) else row for row in config['datasets']]
    if dataset_names != list(CAPACITY_DATASETS):
        raise ValueError('capacity_three_dataset_order_required')
    pool_paths = config['source_pool']['paths']
    dataset_configs = [{'name': dataset, 'source_pool': {
        'manifest': pool_paths['source_pool_manifest'].format(dataset=dataset),
        'database': pool_paths['database'].format(dataset=dataset),
        'source_order': pool_paths['source_order'].format(dataset=dataset)}} for dataset in dataset_names]
    minimum_words = int(config['source_selection']['minimum_words'])
    sources, aliases, hashes, documents, pools, inputs = capacity_load_pools(ROOT, dataset_configs)
    events, inventory, unresolved, missing = capacity_scan_history(ROOT, output, sources, aliases, hashes, documents)
    rows, counts = capacity_classify_sources(sources, events, minimum_words)
    summary = []
    for dataset in CAPACITY_DATASETS:
        count = counts[dataset]
        candidates = count['no_record_candidate']
        row = {'dataset': dataset, **pools[dataset], 'known_contact': count['known_contact'],
               'history_uncertain': count['history_uncertain'], 'below_minimum_words': count['below_minimum_words'],
               'cross_dataset_duplicate': count['cross_dataset_duplicate'], 'no_record_candidate': candidates,
               'preparation_only_any': count['preparation_only_any'], 'preparation_only_candidate': count['preparation_only_candidate'],
               'candidate_without_preparation_record': candidates - count['preparation_only_candidate'],
               'strict_max_balanced_per_group_before_construction': (candidates - count['preparation_only_candidate']) // 2,
               'max_balanced_per_group_before_construction': candidates // 2,
               'target_1000_per_group_candidate_capacity': candidates >= 2000}
        if sum(row[k] for k in ('known_contact', 'history_uncertain', 'below_minimum_words',
                                'cross_dataset_duplicate', 'no_record_candidate')) != row['frozen_source_count']:
            raise RuntimeError('capacity_partition_not_exact:' + dataset)
        summary.append(row)
    inputs.update({str((ROOT / item['path']).resolve()): item['sha256'] for item in inventory})
    inputs[str(args.config.resolve())] = sha256_file(args.config)
    inputs[str(Path(__file__).resolve())] = sha256_file(Path(__file__))
    if any(sha256_file(Path(path)) != digest for path, digest in inputs.items()):
        raise RuntimeError('capacity_input_changed_during_audit')
    report = {'status': 'local_source_capacity_a2_complete', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'source_unit': 'beir_corpus_document', 'minimum_words': minimum_words, 'summary': summary,
              'scope': 'retained artifacts/legacy/research and root records, plus code-archive JSON metadata; exact keys/raw/normalized hashes and conservative abbreviated-ID matching',
              'normalization': 'space-joined casefold split, identical to v24._norm',
              'classification_order': ['known_contact', 'history_uncertain', 'below_minimum_words',
                                       'cross_dataset_duplicate', 'no_record_candidate'],
              'notes': ['candidate/source_order enumerations are not experimental contact',
                        'three-file fixed/prepared-only outputs are listed separately, with no execution record',
                        'failed/superseded and archived evidence included; background index identities included',
                        'old labels/eligible/scores are not used for candidate selection',
                        'no-record candidate count is conditional on retained local history; not a universal fresh guarantee',
                        'capacity is before fact/query construction, not a qualified-source count',
                        'cross-dataset candidate duplicates keep nfcorpus then scidocs then trec-covid for counting only; no split drawn'],
              'history_file_count': len(inventory), 'history_bytes': sum(item['bytes'] for item in inventory),
              'history_categories': dict(Counter(item['category'] for item in inventory)),
              'parse_failures': [item for item in inventory if item['parse_error']],
              'unresolved_target_identity_count': len(unresolved), 'missing_referenced_inputs': missing,
              'unique_missing_referenced_inputs': sorted({name.replace('\\', '/') for _, name in missing}),
              'inputs_unchanged_during_audit': True, 'input_hashes': inputs,
              'code': {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                       'analysis_script_sha256': sha256_file(Path(__file__)), 'uncommitted_analysis_code': True},
              'new_calls': {'victim': 0, 'api': 0, 'retriever': 0, 'nli': 0}, 'new_split_created': False,
              'reproduction_command': '& ' + "'" + sys.executable + "' -X utf8 -B " + ' '.join('"' + arg + '"' for arg in sys.argv)}
    output.mkdir(parents=True, exist_ok=False)
    for name, values in (('capacity.csv', summary), ('history_inventory.csv', inventory), ('unresolved_identities.csv', unresolved)):
        with (output / name).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]) if values else ['file_id', 'source_key'])
            writer.writeheader()
            writer.writerows(values)
    with (output / 'source_audit.jsonl').open('w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
    lines = ['# ReCheck A2 来源容量盘点', '', '本轮只读检查来源身份、文本hash和本地历史记录；未分配新membership或调用模型。', '',
             '| 数据集 | 原始文档 | 池内去重来源 | 已接触 | 历史不明 | 无记录但不足80词 | 跨库重复排除 | 可用候选 | 平衡容量上限 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for row in summary:
        n = row['max_balanced_per_group_before_construction']
        lines.append('| ' + ' | '.join(str(row[k]) for k in ('dataset', 'raw_document_count', 'frozen_source_count',
                      'known_contact', 'history_uncertain', 'below_minimum_words', 'cross_dataset_duplicate', 'no_record_candidate'))
                     + f' | {n}＋{n} |')
    lines += ['', '容量上限仅表示历史隔离和最短长度检查后的候选数，不表示能成功构造同样数量的合格问题。', '',
              f'扫描{len(inventory)}份本地文件；解析失败{len(report["parse_failures"])}份，无法关联到保留池的目标身份{len(unresolved)}条。',
              '“已接触”包括构造、查询、检索背景文档、判分/审核及原开发排除；“历史不明”包括只有分配或文字引用的身份，已保守扣除。',
              '只包含run_config和两个来源/index清单、状态明确在调用前的目录列作仅准备；相关来源另列，不自动当作已调用。', '',
              '| 数据集 | 候选中仅准备未执行 | 完全没有历史分配记录的候选 | 最保守平衡上限 |',
              '|---|---:|---:|---|']
    for row in summary:
        n = row['strict_max_balanced_per_group_before_construction']
        lines.append(f'| {row["dataset"]} | {row["preparation_only_candidate"]} | {row["candidate_without_preparation_record"]} | {n}＋{n} |')
    lines += ['',
              '逐文档身份、词数、互斥状态及证据file_id见[source_audit.jsonl](source_audit.jsonl)；证据路径和hash见[history_inventory.csv](history_inventory.csv)。',
              '未能关联的目标身份见[unresolved_identities.csv](unresolved_identities.csv)，缺失历史输入及范围限制见[report.json](report.json)。', '',
              '以下历史输入在本地未找到，容量因此仍是保留记录范围内的候选上限：', '']
    lines += ['- ' + name for name in report['unique_missing_referenced_inputs']]
    lines += ['',
              '**无记录不等于保证从未接触。** 结论以当前机器保留的记录为边界；删除、未保留或机器外的历史不在保证范围内。',
              '本报告不读取旧membership/eligible/score来确定候选，不修改旧split、配置、响应、判分或冻结artifact。', '',
              '复跑命令：', '', '```powershell', report['reproduction_command'], '```', '输出目录必须为新的诊断目录。', '']
    (output / 'capacity-report.md').write_text('\n'.join(lines), encoding='utf-8')
    report['output_hashes'] = {path.name: sha256_file(path) for path in sorted(output.iterdir())}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'summary': summary, 'history_files': len(inventory),
                      'parse_failures': len(report['parse_failures']), 'new_calls': report['new_calls']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if '--audit-source-capacity' in sys.argv:
        main_source_capacity()
    elif '--offline-a1' in sys.argv:
        main_offline_a1()
    elif '--signed-formal' in sys.argv:
        main_signed_formal()
    elif '--signed-development' in sys.argv:
        main_signed_development()
    else:
        main_scoring()
