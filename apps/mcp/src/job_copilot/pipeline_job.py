import argparse

from job_copilot.ingestion import run_spark_pipeline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    run_spark_pipeline(args.catalog, args.schema)


if __name__ == "__main__":
    main()

