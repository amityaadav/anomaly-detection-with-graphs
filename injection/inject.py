"""Inject or clear failure scenarios via SSM Parameter Store flags."""

import argparse
import json
import sys
from pathlib import Path

import boto3


def load_scenarios() -> dict:
    path = Path(__file__).parent / "scenarios.json"
    with open(path) as f:
        return json.load(f)["scenarios"]


def inject(scenario_id: str, action: str, region: str) -> None:
    scenarios = load_scenarios()

    if scenario_id not in scenarios:
        print(f"Unknown scenario: {scenario_id}")
        print(f"Available: {', '.join(scenarios.keys())}")
        sys.exit(1)

    scenario = scenarios[scenario_id]
    ssm = boto3.client("ssm", region_name=region)

    if action == "enable":
        print(f"Injecting failure: {scenario['name']}")
        for param, value in scenario["ssm_flags"].items():
            ssm.put_parameter(
                Name=param, Value=value, Type="String", Overwrite=True
            )
            print(f"  Set {param} = {value}")
        print("Failure injection active.")

    elif action == "disable":
        print(f"Clearing failure: {scenario['name']}")
        for param in scenario["ssm_flags"]:
            ssm.put_parameter(
                Name=param, Value="false", Type="String", Overwrite=True
            )
            print(f"  Set {param} = false")
        print("Failure cleared.")

    elif action == "status":
        print(f"Scenario: {scenario['name']}")
        for param in scenario["ssm_flags"]:
            try:
                resp = ssm.get_parameter(Name=param)
                value = resp["Parameter"]["Value"]
                print(f"  {param} = {value}")
            except ssm.exceptions.ParameterNotFound:
                print(f"  {param} = (not set)")

    else:
        print(f"Unknown action: {action}. Use enable, disable, or status.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Inject failure scenarios")
    parser.add_argument(
        "--scenario",
        required=True,
        choices=["redis2", "pgpool", "kafka", "vault", "dns", "all"],
        help="Which scenario to inject",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["enable", "disable", "status"],
        help="Enable, disable, or check status",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region",
    )
    args = parser.parse_args()

    if args.scenario == "all":
        scenarios = load_scenarios()
        for sid in scenarios:
            inject(sid, args.action, args.region)
            print()
    else:
        inject(args.scenario, args.action, args.region)


if __name__ == "__main__":
    main()
