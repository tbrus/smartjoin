"""Generate deterministic healthcare-style relational test data for Smartjoin."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from test_datasets.common import (
    COUNTRIES,
    CURRENCIES,
    build_manifest,
    derive_prefixed_numeric,
    dirty_key,
    idf,
    iso,
    pick,
    sample_lines,
    token,
    write_csv,
    write_manifest,
)

PATIENT_STATUS = ["active", "inactive", "archived"]
ENCOUNTER_STATUS = ["scheduled", "arrived", "completed", "cancelled", "no_show"]
CLAIM_STATUS = ["submitted", "review", "approved", "denied", "paid", "voided"]
PAYMENT_STATUS = ["posted", "partial", "paid", "rejected"]
SPECIALTIES = ["family", "cardio", "ortho", "neuro", "derm", "peds"]
FACILITY_TYPES = ["hospital", "clinic", "urgent_care", "lab", "imaging"]
PAYER_TYPES = ["commercial", "government", "self_pay", "worker_comp"]
ADJUST_REASONS = ["contractual", "coding", "timely_filing", "patient_responsibility"]


@dataclass(frozen=True)
class Profile:
    name: str
    n_patients: int
    n_providers: int
    n_facilities: int
    n_payers: int
    n_encounters: int
    n_claims: int
    avg_claim_lines: float


PROFILES: dict[str, Profile] = {
    "tiny": Profile("tiny", 800, 120, 40, 20, 2_000, 1_700, 2.2),
    "small": Profile("small", 15_000, 1_200, 300, 120, 70_000, 62_000, 2.7),
    "medium": Profile("medium", 45_000, 4_000, 1_000, 400, 220_000, 190_000, 3.1),
    "large": Profile("large", 120_000, 10_000, 2_500, 1_200, 900_000, 760_000, 3.3),
}


@dataclass(frozen=True)
class Config:
    out_dir: Path
    seed: int
    profile: str
    n_patients: int
    n_providers: int
    n_facilities: int
    n_payers: int
    n_encounters: int
    n_claims: int
    avg_claim_lines: float
    pct_missing: float
    pct_duplicates: float
    pct_dirty_keys: float
    pct_derived_keys: float
    pct_derived_both_sides: float
    pct_inconsistent_types: float
    include_json: bool
    max_json_encounters: int


def maybe_derived_id(
    rng: random.Random,
    value: str,
    *,
    probability: float,
    prefix_override: str,
    styles: tuple[str, ...] = ("dash_lower", "underscore_upper", "hash_lower"),
) -> str:
    if rng.random() >= probability:
        return value
    style = rng.choice(list(styles))
    return derive_prefixed_numeric(value, style=style, prefix_override=prefix_override)


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        description="Generate deterministic healthcare-style performance data."
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--profile", choices=sorted(PROFILES.keys()), default="small")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-patients", type=int, default=None)
    parser.add_argument("--n-providers", type=int, default=None)
    parser.add_argument("--n-facilities", type=int, default=None)
    parser.add_argument("--n-payers", type=int, default=None)
    parser.add_argument("--n-encounters", type=int, default=None)
    parser.add_argument("--n-claims", type=int, default=None)
    parser.add_argument("--avg-claim-lines", type=float, default=None)
    parser.add_argument("--pct-missing", type=float, default=0.02)
    parser.add_argument("--pct-duplicates", type=float, default=0.01)
    parser.add_argument("--pct-dirty-keys", type=float, default=0.04)
    parser.add_argument("--pct-derived-keys", type=float, default=0.2)
    parser.add_argument("--pct-derived-both-sides", type=float, default=0.1)
    parser.add_argument("--pct-inconsistent-types", type=float, default=0.03)
    parser.add_argument("--include-json", action="store_true", default=False)
    parser.add_argument("--max-json-encounters", type=int, default=40_000)
    args = parser.parse_args(argv)
    profile = PROFILES[args.profile]
    out_dir = args.out_dir or (Path("perf_data") / "datasets" / f"health_{args.profile}")
    return Config(
        out_dir=out_dir,
        seed=args.seed,
        profile=args.profile,
        n_patients=args.n_patients or profile.n_patients,
        n_providers=args.n_providers or profile.n_providers,
        n_facilities=args.n_facilities or profile.n_facilities,
        n_payers=args.n_payers or profile.n_payers,
        n_encounters=args.n_encounters or profile.n_encounters,
        n_claims=args.n_claims or profile.n_claims,
        avg_claim_lines=args.avg_claim_lines or profile.avg_claim_lines,
        pct_missing=args.pct_missing,
        pct_duplicates=args.pct_duplicates,
        pct_dirty_keys=args.pct_dirty_keys,
        pct_derived_keys=args.pct_derived_keys,
        pct_derived_both_sides=args.pct_derived_both_sides,
        pct_inconsistent_types=args.pct_inconsistent_types,
        include_json=args.include_json,
        max_json_encounters=args.max_json_encounters,
    )


def generate_dataset(config: Config) -> dict[str, int]:
    rng = random.Random(config.seed)
    out_dir = config.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    base = date(2021, 1, 1)
    counts: dict[str, int] = {}

    def maybe_dup(row: dict[str, Any]) -> Iterable[dict[str, Any]]:
        yield row
        if rng.random() < config.pct_duplicates:
            yield row.copy()

    counts["patients"] = write_csv(
        out_dir / "patients.csv",
        ["patient_key", "patient_alt_id", "status", "country", "region_code", "created_date"],
        (
            dup
            for i in range(1, config.n_patients + 1)
            for dup in maybe_dup(
                {
                    "patient_key": idf("PT", i, 8),
                    "patient_alt_id": (
                        idf("PT", i, 8) if rng.random() > 0.18 else f"PAT{idf('', i, 8)}"
                    ),
                    "status": pick(rng, PATIENT_STATUS, [84, 12, 4]),
                    "country": pick(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                    "region_code": f"R{rng.randint(1, 40):02d}",
                    "created_date": iso(base, rng.randint(0, 1600)),
                }
            )
        ),
    )

    counts["providers"] = write_csv(
        out_dir / "providers.csv",
        ["provider_id", "specialty", "status", "country", "region_code", "created_date"],
        (
            dup
            for i in range(1, config.n_providers + 1)
            for dup in maybe_dup(
                {
                    "provider_id": idf("PRV", i, 7),
                    "specialty": rng.choice(SPECIALTIES),
                    "status": pick(rng, ["active", "inactive", "leave"], [85, 10, 5]),
                    "country": pick(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                    "region_code": f"R{rng.randint(1, 40):02d}",
                    "created_date": iso(base, rng.randint(0, 1600)),
                }
            )
        ),
    )

    counts["facilities"] = write_csv(
        out_dir / "facilities.csv",
        ["facility_id", "facility_type", "status", "country", "region_code", "created_date"],
        (
            dup
            for i in range(1, config.n_facilities + 1)
            for dup in maybe_dup(
                {
                    "facility_id": idf("FAC", i, 6),
                    "facility_type": rng.choice(FACILITY_TYPES),
                    "status": pick(rng, ["active", "inactive", "closed"], [88, 8, 4]),
                    "country": pick(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                    "region_code": f"R{rng.randint(1, 40):02d}",
                    "created_date": iso(base, rng.randint(0, 1600)),
                }
            )
        ),
    )

    counts["payers"] = write_csv(
        out_dir / "payers.csv",
        ["payer_id", "payer_type", "status", "country", "region_code", "effective_date"],
        (
            dup
            for i in range(1, config.n_payers + 1)
            for dup in maybe_dup(
                {
                    "payer_id": idf("PY", i, 6),
                    "payer_type": rng.choice(PAYER_TYPES),
                    "status": pick(rng, ["active", "inactive", "paused"], [86, 10, 4]),
                    "country": pick(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                    "region_code": f"R{rng.randint(1, 40):02d}",
                    "effective_date": iso(base, rng.randint(0, 1600)),
                }
            )
        ),
    )

    def encounter_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, config.n_encounters + 1):
            patient = idf("PT", rng.randint(1, config.n_patients), 8)
            provider = idf("PRV", rng.randint(1, config.n_providers), 7)
            facility = idf("FAC", rng.randint(1, config.n_facilities), 6)
            patient = maybe_derived_id(
                rng,
                patient,
                probability=config.pct_derived_keys,
                prefix_override="pat",
            )
            facility = maybe_derived_id(
                rng,
                facility,
                probability=config.pct_derived_keys * 0.6,
                prefix_override="facility",
            )
            if rng.random() < config.pct_dirty_keys:
                patient = dirty_key(rng, patient)
            if rng.random() < config.pct_dirty_keys * 0.5:
                facility = dirty_key(rng, facility)
            number: Any = i if rng.random() > config.pct_inconsistent_types else str(i)
            enc_date = iso(base, rng.randint(0, 1700))
            row = {
                "encounter_id": idf("ENC", i, 10),
                "patient_key_id": patient,
                "provider_key_id": provider,
                "facility_key_id": facility,
                "encounter_number": number,
                "status": pick(rng, ENCOUNTER_STATUS, [10, 20, 60, 7, 3]),
                "country": pick(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                "region_code": f"R{rng.randint(1, 40):02d}",
                "encounter_date": enc_date,
                "updated_date": iso(date.fromisoformat(enc_date), rng.randint(0, 30)),
            }
            yield from maybe_dup(row)

    counts["encounters"] = write_csv(
        out_dir / "encounters.csv",
        [
            "encounter_id",
            "patient_key_id",
            "provider_key_id",
            "facility_key_id",
            "encounter_number",
            "status",
            "country",
            "region_code",
            "encounter_date",
            "updated_date",
        ],
        encounter_rows(),
    )

    def claim_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, config.n_claims + 1):
            encounter = idf("ENC", rng.randint(1, config.n_encounters), 10)
            payer = idf("PY", rng.randint(1, config.n_payers), 6)
            encounter = maybe_derived_id(
                rng,
                encounter,
                probability=config.pct_derived_keys,
                prefix_override="enc",
            )
            payer = maybe_derived_id(
                rng,
                payer,
                probability=config.pct_derived_keys * 0.6,
                prefix_override="payer",
            )
            if rng.random() < config.pct_dirty_keys:
                encounter = dirty_key(rng, encounter)
            if rng.random() < config.pct_dirty_keys * 0.6:
                payer = dirty_key(rng, payer)
            sub = iso(base, rng.randint(0, 1700))
            row = {
                "claim_id": idf("CLM", i, 10),
                "encounter_id": encounter,
                "payer_key_id": payer,
                "status": pick(rng, CLAIM_STATUS, [8, 15, 28, 9, 35, 5]),
                "currency": pick(rng, CURRENCIES, [35, 55, 5, 5]),
                "total_amount": round(max(20.0, rng.lognormvariate(4.2, 0.8)), 2),
                "submitted_date": sub,
                "processed_date": iso(date.fromisoformat(sub), rng.randint(0, 45)),
                "region_code": f"R{rng.randint(1, 40):02d}",
            }
            yield from maybe_dup(row)

    counts["claims"] = write_csv(
        out_dir / "claims.csv",
        [
            "claim_id",
            "encounter_id",
            "payer_key_id",
            "status",
            "currency",
            "total_amount",
            "submitted_date",
            "processed_date",
            "region_code",
        ],
        claim_rows(),
    )

    def claim_line_rows() -> Iterable[dict[str, Any]]:
        for i in range(1, config.n_claims + 1):
            claim = idf("CLM", i, 10)
            for line_no in range(1, sample_lines(rng, config.avg_claim_lines) + 1):
                row = {
                    "claim_id": claim,
                    "line_no": line_no,
                    "service_code": f"SVC-{token(rng, 6)}",
                    "units": rng.randint(1, 5),
                    "charge_amount": round(max(5.0, rng.lognormvariate(3.9, 0.7)), 2),
                    "status": pick(rng, ["open", "closed", "void"], [35, 60, 5]),
                }
                yield from maybe_dup(row)

    counts["claim_lines"] = write_csv(
        out_dir / "claim_lines.csv",
        ["claim_id", "line_no", "service_code", "units", "charge_amount", "status"],
        claim_line_rows(),
    )

    pay_count = 0
    adj_count = 0
    with (
        (out_dir / "payments.csv").open("w", newline="", encoding="utf-8") as pay_f,
        (out_dir / "adjustments.csv").open("w", newline="", encoding="utf-8") as adj_f,
    ):
        pay_w = csv.DictWriter(
            pay_f,
            fieldnames=[
                "payment_id",
                "claim_key_id",
                "status",
                "paid_amount",
                "paid_date",
                "currency",
            ],
        )
        adj_w = csv.DictWriter(
            adj_f,
            fieldnames=[
                "adjustment_id",
                "payment_id",
                "adjustment_amount",
                "reason",
                "status",
                "created_date",
            ],
        )
        pay_w.writeheader()
        adj_w.writeheader()
        for i in range(1, config.n_claims + 1):
            if rng.random() < 0.15:
                continue
            claim = maybe_derived_id(
                rng,
                idf("CLM", i, 10),
                probability=config.pct_derived_keys,
                prefix_override="claim",
            )
            if rng.random() < config.pct_dirty_keys:
                claim = dirty_key(rng, claim)
            paid = iso(base, rng.randint(0, 1800))
            payment_id_canonical = idf("PAY", i, 10)
            payment_id = payment_id_canonical
            adjustment_payment_key = payment_id_canonical
            if rng.random() < config.pct_derived_both_sides:
                payment_id = maybe_derived_id(
                    rng,
                    payment_id_canonical,
                    probability=1.0,
                    prefix_override="pay",
                    styles=("dash_lower", "hash_lower"),
                )
                adjustment_payment_key = maybe_derived_id(
                    rng,
                    payment_id_canonical,
                    probability=1.0,
                    prefix_override="payment",
                    styles=("underscore_upper", "slash_lower", "space_dash"),
                )
                if adjustment_payment_key == payment_id:
                    adjustment_payment_key = derive_prefixed_numeric(
                        payment_id_canonical,
                        style="underscore_upper",
                        prefix_override="payment",
                    )
            payment = {
                "payment_id": payment_id,
                "claim_key_id": claim,
                "status": pick(rng, PAYMENT_STATUS, [18, 14, 62, 6]),
                "paid_amount": round(max(5.0, rng.lognormvariate(4.0, 0.75)), 2),
                "paid_date": paid,
                "currency": pick(rng, CURRENCIES, [35, 55, 5, 5]),
            }
            pay_w.writerow(payment)
            pay_count += 1
            if rng.random() < config.pct_duplicates:
                pay_w.writerow(payment)
                pay_count += 1
            if payment["status"] in {"partial", "rejected"} or rng.random() < 0.22:
                adjustment = {
                    "adjustment_id": idf("ADJ", i, 10),
                    "payment_id": adjustment_payment_key,
                    "adjustment_amount": round(max(1.0, rng.lognormvariate(2.2, 0.6)), 2),
                    "reason": rng.choice(ADJUST_REASONS),
                    "status": pick(rng, ["open", "posted"], [35, 65]),
                    "created_date": iso(date.fromisoformat(paid), rng.randint(0, 20)),
                }
                adj_w.writerow(adjustment)
                adj_count += 1
                if rng.random() < config.pct_duplicates:
                    adj_w.writerow(adjustment)
                    adj_count += 1

    counts["payments"] = pay_count
    counts["adjustments"] = adj_count

    if config.include_json:
        json_n = min(config.max_json_encounters, config.n_encounters)
        rows = []
        for i in range(1, json_n + 1):
            rows.append(
                {
                    "encounterId": idf("ENC", i, 10),
                    "patientId": idf("PT", rng.randint(1, config.n_patients), 8),
                    "meta": {
                        "status": pick(rng, ENCOUNTER_STATUS, [10, 20, 60, 7, 3]),
                        "country": pick(rng, COUNTRIES, [18, 12, 10, 9, 8, 7, 7, 7, 6, 6]),
                        "encounterDate": iso(base, rng.randint(0, 1700)),
                    },
                }
            )
        (out_dir / "encounters_nested.json").write_text(json.dumps(rows), encoding="utf-8")
        counts["encounters_nested_json"] = json_n

    return counts


def write_docs(config: Config, counts: dict[str, int]) -> None:
    out_dir = config.out_dir
    config_dict = asdict(config)
    config_dict["out_dir"] = str(config.out_dir)
    core_relationships = [
        {
            "from_table": "encounters",
            "from_column": "patient_key_id",
            "to_table": "patients",
            "to_column": "patient_key",
            "relationship": "many_to_one",
            "dirty_keys_present": True,
            "join_type": "derived_mixed",
            "derived_side": "from_table_only",
        },
        {
            "from_table": "encounters",
            "from_column": "provider_key_id",
            "to_table": "providers",
            "to_column": "provider_id",
            "relationship": "many_to_one",
            "dirty_keys_present": False,
            "join_type": "direct",
        },
        {
            "from_table": "encounters",
            "from_column": "facility_key_id",
            "to_table": "facilities",
            "to_column": "facility_id",
            "relationship": "many_to_one",
            "dirty_keys_present": True,
            "join_type": "derived_mixed",
            "derived_side": "from_table_only",
        },
        {
            "from_table": "claims",
            "from_column": "encounter_id",
            "to_table": "encounters",
            "to_column": "encounter_id",
            "relationship": "many_to_one",
            "dirty_keys_present": True,
            "join_type": "derived_mixed",
            "derived_side": "from_table_only",
        },
        {
            "from_table": "claims",
            "from_column": "payer_key_id",
            "to_table": "payers",
            "to_column": "payer_id",
            "relationship": "many_to_one",
            "dirty_keys_present": True,
            "join_type": "derived_mixed",
            "derived_side": "from_table_only",
        },
        {
            "from_table": "claim_lines",
            "from_column": "claim_id",
            "to_table": "claims",
            "to_column": "claim_id",
            "relationship": "many_to_one",
            "dirty_keys_present": False,
            "join_type": "direct",
        },
        {
            "from_table": "payments",
            "from_column": "claim_key_id",
            "to_table": "claims",
            "to_column": "claim_id",
            "relationship": "many_to_one",
            "dirty_keys_present": True,
            "join_type": "derived_mixed",
            "derived_side": "from_table_only",
        },
        {
            "from_table": "adjustments",
            "from_column": "payment_id",
            "to_table": "payments",
            "to_column": "payment_id",
            "relationship": "many_to_one",
            "dirty_keys_present": False,
            "join_type": "derived_mixed",
            "derived_side": "both_tables",
        },
    ]
    if config.include_json:
        core_relationships.append(
            {
                "from_table": "encounters_nested",
                "from_column": "patientId",
                "to_table": "patients",
                "to_column": "patient_key",
                "relationship": "many_to_one",
                "dirty_keys_present": False,
                "join_type": "direct",
            }
        )

    traps = {
        "shared_low_cardinality_columns": ["status", "country", "currency"],
        "date_like_columns": [
            "created_date",
            "updated_date",
            "encounter_date",
            "submitted_date",
            "processed_date",
            "paid_date",
            "effective_date",
        ],
        "misleading_name_pairs": [
            {
                "left": "patients.patient_alt_id",
                "right": "encounters.patient_key_id",
                "reason": "Similar semantics but different namespace.",
            }
        ],
        "overlapping_value_traps": [
            {
                "columns": ["facilities.region_code", "payers.region_code"],
                "value_domain": "R01-R40",
                "expected_overlap": "very_high",
            }
        ],
    }
    if config.include_json:
        traps["misleading_name_pairs"].append(
            {
                "left": "encounters.patient_key_id",
                "right": "encounters_nested.patientId",
                "reason": "Naming convention mismatch across formats.",
            }
        )
    manifest = build_manifest(
        generator="scripts/test_datasets/domains/health.py",
        config=config_dict,
        row_counts=counts,
        trap_columns=["status", "country", "currency", "region_code", "encounter_date"],
        ground_truth={
            "core_relationships": core_relationships,
            "composite_key_candidates": [
                {
                    "table": "claim_lines",
                    "columns": ["claim_id", "line_no"],
                    "notes": "Near-unique with controlled duplicates.",
                }
            ],
            "traps": traps,
        },
    )
    write_manifest(out_dir, manifest)
    legacy_readme = out_dir / "README.md"
    if legacy_readme.exists():
        legacy_readme.unlink()


def main(argv: list[str] | None = None) -> None:
    config = parse_args(argv)
    counts = generate_dataset(config)
    write_docs(config, counts)
    print(f"Generated dataset at: {config.out_dir.resolve()}")
    for table_name, count in counts.items():
        print(f"  - {table_name}: {count:,}")


if __name__ == "__main__":
    main()
