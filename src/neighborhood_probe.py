"""LLM 邻域探针：为输入生成无损同义邻域。"""
import json
import re


class NeighborhoodProbe:
    """为每个输入生成一组语义保持的近邻文本。"""

    def __init__(self, llm_client, default_neighbors=5):
        self.llm = llm_client
        self.default_neighbors = default_neighbors

    def generate(self, text, k=None):
        if self.llm is None:
            raise RuntimeError("Neighborhood generation requires a configured LLM client.")
        k = k or self.default_neighbors
        prompt = (
            f"Generate {k} meaning-preserving paraphrases of the text below. "
            "Keep factual content unchanged. Output ONLY a JSON array of strings.\n\n"
            f"Text:\n{text[:1200]}"
        )
        replies = self.llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=max(160, k * 80),
            n=1,
        )
        raw = replies[0] if replies else "[]"
        neighbors = self._parse_neighbors(raw)

        deduped = []
        seen = {text.strip()}
        for item in neighbors:
            cleaned = item.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                deduped.append(cleaned)
            if len(deduped) >= k:
                break
        if not deduped:
            raise RuntimeError("LLM returned no valid neighborhood paraphrases.")
        return deduped

    @staticmethod
    def _parse_neighbors(raw_text):
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass

        match = re.search(r"\[[\s\S]*\]", raw_text)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                pass

        lines = []
        for line in raw_text.splitlines():
            cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            if cleaned:
                lines.append(cleaned)
        return lines
