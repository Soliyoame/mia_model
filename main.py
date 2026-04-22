"""CLI entry for the generative robust auditor."""

import argparse

from src.model_config import get_model_config_defaults


MODEL_DEFAULTS = get_model_config_defaults()


def build_common_parser(common):
    common.add_argument("--dataset", type=str, default=None, help="Dataset name")
    common.add_argument("--device", type=str, default="auto", help="Device: auto / cpu / cuda")
    common.add_argument("--verbose", action="store_true", help="Print verbose logs")
    common.add_argument("--llm-api-key", type=str, default=None, help="LLM API key")
    common.add_argument("--llm-base-url", type=str, default=None, help="LLM API base URL")
    common.add_argument("--llm-model", type=str, default=None, help="LLM model name")
    common.add_argument(
        "--victim-model-name",
        type=str,
        default=MODEL_DEFAULTS["victim_model_name"],
        help="Victim model name or local path",
    )
    common.add_argument(
        "--reference-model-name",
        type=str,
        default=MODEL_DEFAULTS["reference_model_name"],
        help="Reference model name or local path",
    )
    common.add_argument("--reference-device", type=str, default=None, help="Optional device for the reference model")
    common.add_argument("--victim-path", type=str, default=None, help="Directory for victim weights")
    common.add_argument("--auditor-path", type=str, default=None, help="Path for auditor weights")


def make_pipeline(args):
    from src.pipeline import Pipeline

    return Pipeline(
        device=args.device,
        retrain_victim=getattr(args, "retrain", False),
        llm_api_key=args.llm_api_key,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        victim_model_name=args.victim_model_name,
        reference_model_name=args.reference_model_name,
        neighbor_count=getattr(args, "neighbor_count", 8),
        victim_ratio=getattr(args, "victim_ratio", 1.0 / 3.0),
        spoof_ratio=getattr(args, "spoof_ratio", 0.5),
        max_samples_per_dataset=getattr(args, "max_samples_per_dataset", 300),
        max_spoof_per_dataset=getattr(args, "max_spoof_per_dataset", 100),
        max_spoof_attempts=getattr(args, "max_spoof_attempts", 6),
        max_spoof_rounds=getattr(args, "max_spoof_rounds", 600),
        spoof_threshold=getattr(args, "spoof_threshold", None),
        victim_epochs=getattr(args, "victim_epochs", 2),
        victim_train_max_length=getattr(args, "victim_train_max_length", None),
        victim_min_train_max_length=getattr(args, "victim_min_train_max_length", 64),
        victim_device_map=getattr(args, "victim_device_map", None),
        reference_device=getattr(args, "reference_device", None),
        victim_path=args.victim_path,
        auditor_path=args.auditor_path,
        preload_dataset_name=getattr(args, "dataset", None),
    )


def main():
    parser = argparse.ArgumentParser(description="Generative robust MIA auditor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train", help="Train victim and auditor")
    build_common_parser(train_parser)
    train_parser.add_argument("--retrain", action="store_true", help="Force victim retraining")
    train_parser.add_argument(
        "--spoof-threshold",
        type=float,
        required=True,
        help="Required spoof member-probability threshold (paper setting usually 0.80)",
    )
    train_parser.add_argument("--neighbor-count", type=int, default=8, help="Number of neighborhood probes")
    train_parser.add_argument(
        "--victim-ratio",
        type=float,
        default=1.0 / 3.0,
        help="Fraction of raw samples used as true members / victim fine-tuning pool",
    )
    train_parser.add_argument(
        "--spoof-ratio",
        type=float,
        default=0.5,
        help="Fraction of the non-member remainder allocated to spoof source texts",
    )
    train_parser.add_argument("--victim-epochs", type=int, default=2, help="Victim fine-tuning epochs")
    train_parser.add_argument(
        "--victim-train-max-length",
        type=int,
        default=None,
        help="Initial max token length for victim fine-tuning; defaults to the model max_length setting",
    )
    train_parser.add_argument(
        "--victim-min-train-max-length",
        type=int,
        default=64,
        help="Lower bound for automatic OOM fallback during victim fine-tuning",
    )
    train_parser.add_argument(
        "--victim-device-map",
        type=str,
        default=None,
        help="Optional Hugging Face device_map for victim loading, e.g. auto or balanced",
    )
    train_parser.add_argument("--max-spoof-attempts", type=int, default=6, help="Maximum attempts per spoof sample")
    train_parser.add_argument("--max-spoof-rounds", type=int, default=600, help="Global maximum spoof regeneration rounds")
    train_parser.add_argument("--max-samples-per-dataset", type=int, default=300, help="Maximum raw samples per dataset")
    train_parser.add_argument("--max-spoof-per-dataset", type=int, default=100, help="Maximum spoof source texts per dataset")

    infer_parser = subparsers.add_parser("infer", help="Run inference for one text")
    build_common_parser(infer_parser)
    infer_parser.add_argument("--text", type=str, required=True, help="Input text for membership inference")
    infer_parser.add_argument("--neighbor-count", type=int, default=8, help="Number of neighborhood probes")

    args = parser.parse_args()
    pipeline = make_pipeline(args)

    if args.command == "train":
        train_result = pipeline.train(dataset_name=args.dataset, verbose=args.verbose)
        print_train_result(train_result)
        return

    if args.command == "infer":
        result = pipeline.infer(args.text, verbose=args.verbose)
        print_infer_result(result)
        return

    parser.error(f"Unsupported command: {args.command}")


def print_train_result(result):
    print(f"\n{'=' * 60}")
    print("Training completed")
    print(f"  datasets: {', '.join(result['dataset_names'])}")
    print(f"  victim_train_samples: {result['victim_train_samples']}")
    print(f"  auditor_samples:      {result['auditor_samples']}")
    print(f"  spoof_threshold:      {result['spoof_threshold']:.4f}")
    print(f"  victim_path:          {result['victim_path']}")
    print(f"  auditor_path:         {result['auditor_path']}")
    print(f"  spoof_log_path:       {result['spoof_log_path']}")
    print("  calibration:")
    for key, value in result["calibration"].items():
        print(f"    - {key}: {value}")
    print("  per-dataset summary:")
    for dataset_name, stats in result["build_summary"].items():
        print(f"    - {dataset_name}")
        for key, value in stats.items():
            print(f"      {key}: {value}")
    print("  overall stats:")
    for key, value in result["overall_stats"].items():
        print(f"    - {key}: {value}")
    print("  metrics:")
    for key, value in result["metrics"].items():
        print(f"    - {key}: {value:.6f}")
    print(f"{'=' * 60}")


def print_infer_result(result):
    print(f"\n{'=' * 60}")
    print(f"prediction: {'member' if result['prediction'] == 1 else 'non-member'}")
    print(f"member_prob: {result['member_prob']:.4f}")
    print(f"confidence: {result['confidence']:.4f}")
    print(f"loss_vic: {result['loss_vic']:.6f}")
    print(f"loss_base: {result['loss_base']:.6f}")
    print(f"mean_neighbor_loss_vic: {result['mean_neighbor_loss_vic']:.6f}")
    print(f"feature_vector: {result['feature_vector']}")
    if result.get("neighbors"):
        print("neighbors:")
        for index, neighbor in enumerate(result["neighbors"], start=1):
            print(f"  {index}. {neighbor}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
