import boto3
import json

CLUSTER_ARN = "arn:aws:rds:us-east-1:867344470917:cluster:iqg-aurora-cluster"
SECRET_ARN  = "arn:aws:secretsmanager:us-east-1:867344470917:secret:AuroraSecret41E6E877-ogZqDVP4P1dt-JcOo7c"
REGION      = "us-east-1"

client = boto3.client("rds-data", region_name=REGION)

def execute(sql, database="txndb", params=None):
    kwargs = dict(
        resourceArn=CLUSTER_ARN,
        secretArn=SECRET_ARN,
        database=database,
        sql=sql,
    )
    if params:
        kwargs["parameters"] = params
    r = client.execute_statement(**kwargs)
    return r

print("Step 1: Creating plandb database...")
execute("CREATE DATABASE plandb", database="txndb")
print("  ✅ plandb created")

print("Step 2: Creating TXN_DB tables in txndb...")

execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id     VARCHAR(128) PRIMARY KEY,
    email_hash  VARCHAR(64)  NOT NULL,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    consent_at  TIMESTAMP
)
""")
print("  ✅ users table")

execute("""
CREATE TABLE IF NOT EXISTS submissions (
    submission_id       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             VARCHAR(128) NOT NULL REFERENCES users(user_id),
    age                 INT          NOT NULL,
    category            VARCHAR(20)  NOT NULL,
    family_composition  VARCHAR(50),
    lifestyle_json      JSONB,
    pre_existing_json   JSONB,
    target_si           BIGINT,
    budget_premium      BIGINT,
    created_at          TIMESTAMP    NOT NULL DEFAULT NOW()
)
""")
print("  ✅ submissions table")

execute("""
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id   UUID         NOT NULL REFERENCES submissions(submission_id),
    user_id         VARCHAR(128) NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'QUEUED',
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
)
""")
print("  ✅ transactions table")

execute("""
CREATE TABLE IF NOT EXISTS plan_selections (
    selection_id    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id  UUID         NOT NULL REFERENCES transactions(transaction_id),
    plan_id         VARCHAR(20)  NOT NULL,
    selected_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    rank_shown      INT,
    compared_against JSONB
)
""")
print("  ✅ plan_selections table")

execute("""
CREATE TABLE IF NOT EXISTS audit_log (
    event_id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id  UUID,
    event_type      VARCHAR(50)  NOT NULL,
    actor           VARCHAR(128),
    payload_hash    VARCHAR(64),
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
)
""")
print("  ✅ audit_log table")

print("Step 3: Creating plans table in plandb...")
execute("""
CREATE TABLE IF NOT EXISTS plans (
    plan_id                 VARCHAR(20)   PRIMARY KEY,
    plan_name               VARCHAR(100)  NOT NULL,
    category                VARCHAR(20)   NOT NULL CHECK (category IN ('individual','family','senior')),
    tier                    VARCHAR(20)   NOT NULL CHECK (tier IN ('silver','gold','platinum')),
    min_age                 INT           NOT NULL,
    max_age                 INT           NOT NULL,
    sum_insured             BIGINT        NOT NULL,
    annual_premium_base     BIGINT        NOT NULL,
    co_payment_pct          INT           NOT NULL DEFAULT 0,
    room_rent_limit         VARCHAR(50)   NOT NULL,
    ped_waiting_months      INT           NOT NULL,
    initial_waiting_days    INT           NOT NULL DEFAULT 30,
    no_claim_bonus_pct      INT           NOT NULL DEFAULT 10,
    max_ncb_pct             INT           NOT NULL DEFAULT 50,
    restoration_benefit     BOOLEAN       NOT NULL DEFAULT FALSE,
    daycare_covered         BOOLEAN       NOT NULL DEFAULT TRUE,
    ambulance_cover         INT           NOT NULL DEFAULT 2000,
    ayush_covered           BOOLEAN       NOT NULL DEFAULT TRUE,
    maternity_covered       BOOLEAN       NOT NULL DEFAULT FALSE,
    annual_checkup          BOOLEAN       NOT NULL DEFAULT TRUE,
    network_hospitals       INT           NOT NULL,
    critical_illness_cover  BOOLEAN       NOT NULL DEFAULT FALSE,
    teleconsult             BOOLEAN       NOT NULL DEFAULT TRUE,
    policy_tenure_options   VARCHAR(20)   NOT NULL DEFAULT '1/2/3',
    renewability            VARCHAR(20)   NOT NULL DEFAULT 'Lifelong',
    key_exclusions          TEXT          NOT NULL,
    best_for                VARCHAR(200)  NOT NULL
)
""", database="plandb")
print("  ✅ plans table in plandb")

print("Step 4: Seeding 30 SwiftCare plans...")
plans = [
  ("IND-SLV-001","SwiftCare Shield — Silver","individual","silver",18,45,500000,8500,0,"Single AC",24,30,10,50,False,True,2000,True,False,True,7000,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Young healthy individual, first-time buyer, tight budget"),
  ("IND-SLV-002","SwiftCare Shield — Silver Plus","individual","silver",18,50,750000,11200,0,"Single AC",24,30,10,50,False,True,2500,True,False,True,7500,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Young professional wanting slightly higher cover"),
  ("IND-GLD-003","SwiftCare Guard — Gold","individual","gold",18,55,1000000,16500,0,"Single private",24,30,15,75,True,True,3000,True,False,True,8000,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Mid-age individual wanting restoration and higher room"),
  ("IND-GLD-004","SwiftCare Guard — Gold Plus","individual","gold",25,55,1500000,22000,0,"Single private",24,30,15,75,True,True,3500,True,False,True,8500,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Professional 25-55 needing 15L cover with restoration"),
  ("IND-GLD-005","SwiftCare Guard — Gold Max","individual","gold",25,55,2000000,28500,0,"No limit",24,30,20,100,True,True,4000,True,False,True,9000,True,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","High-income individual wanting top gold features and CI"),
  ("IND-PLT-006","SwiftCare Premier — Platinum","individual","platinum",18,60,3000000,38000,0,"No limit",12,30,25,100,True,True,5000,True,False,True,10000,True,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Premium buyer wanting max cover CI and no room limit"),
  ("IND-PLT-007","SwiftCare Premier — Platinum Elite","individual","platinum",18,60,5000000,55000,0,"No limit",12,30,25,100,True,True,7500,True,False,True,10000,True,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Highest-tier individual with 50L cover all benefits"),
  ("IND-SLV-008","SwiftCare Young Star — Silver","individual","silver",18,35,500000,6800,0,"Shared",36,30,10,50,False,True,1500,True,False,False,5000,False,False,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse,Maternity","18-35 youth minimal budget basic hospitalisation"),
  ("IND-GLD-009","SwiftCare Women Care — Gold","individual","gold",18,50,1000000,17500,0,"Single private",24,30,15,75,True,True,3500,True,True,True,8500,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Women 18-50 needing maternity and standard gold cover"),
  ("IND-PLT-010","SwiftCare Diabetes Shield — Platinum","individual","platinum",25,60,2000000,42000,0,"Single private",6,30,20,100,True,True,5000,True,False,True,9000,True,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Individual with diabetes pre-existing condition short PED wait"),
  ("FAM-SLV-001","SwiftCare Family Shield — Silver","family","silver",18,55,500000,14500,0,"Shared",24,30,10,50,False,True,2000,True,False,True,6000,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse,Maternity","Small family 2A+1C entry-level floater"),
  ("FAM-SLV-002","SwiftCare Family Shield — Silver Plus","family","silver",18,55,750000,18500,0,"Single AC",24,30,10,50,False,True,2500,True,False,True,7000,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse,Maternity","Family 2A+2C wanting 7.5L shared cover"),
  ("FAM-GLD-003","SwiftCare Family Guard — Gold","family","gold",18,60,1000000,26000,0,"Single private",24,30,15,75,True,True,3500,True,True,True,8000,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Family of 4 maternity needed gold features"),
  ("FAM-GLD-004","SwiftCare Family Guard — Gold Plus","family","gold",18,60,1500000,33000,0,"Single private",24,30,15,75,True,True,4000,True,True,True,8500,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Growing family 2A+3C 15L floater maternity"),
  ("FAM-GLD-005","SwiftCare Family Guard — Gold Max","family","gold",18,60,2000000,42000,0,"No limit",24,30,20,100,True,True,4500,True,True,True,9000,True,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Family wanting 20L maternity CI no room limit"),
  ("FAM-PLT-006","SwiftCare Family Premier — Platinum","family","platinum",18,65,3000000,58000,0,"No limit",12,30,25,100,True,True,6000,True,True,True,10000,True,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Premium family floater 30L all features short PED"),
  ("FAM-PLT-007","SwiftCare Family Premier — Platinum Elite","family","platinum",18,65,5000000,82000,0,"No limit",12,30,25,100,True,True,7500,True,True,True,10000,True,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Top-of-range family plan 50L every benefit"),
  ("FAM-SLV-008","SwiftCare New Parent Care — Silver","family","silver",18,40,750000,16000,0,"Single AC",24,30,10,50,False,True,2500,True,True,True,7000,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Young couple planning family maternity priority"),
  ("FAM-GLD-009","SwiftCare Joint Family — Gold","family","gold",18,65,2000000,48000,0,"Single private",24,30,15,75,True,True,4500,True,False,True,9000,False,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Large joint family 2A+parents+kids under one floater"),
  ("FAM-PLT-010","SwiftCare Super Family — Platinum","family","platinum",18,65,3000000,65000,0,"No limit",12,30,25,100,True,True,6500,True,True,True,10000,True,True,"1/2/3","Lifelong","Cosmetic surgery,Dental,Substance abuse","Family with senior parents needing high cover and maternity"),
  ("SEN-SLV-001","SwiftCare Silver Years — Silver","senior","silver",60,75,300000,18000,20,"Shared",12,30,5,25,False,True,2000,True,False,True,5000,False,False,"1/2","Up to 75","Cosmetic surgery,Dental,Substance abuse,Maternity","Senior 60-75 budget plan 20 percent co-pay"),
  ("SEN-SLV-002","SwiftCare Silver Years — Silver Plus","senior","silver",60,75,500000,24000,20,"Single AC",12,30,5,25,False,True,2500,True,False,True,6000,False,True,"1/2","Up to 75","Cosmetic surgery,Dental,Substance abuse,Maternity","Senior needing 5L teleconsult manageable premium"),
  ("SEN-GLD-003","SwiftCare Golden Years — Gold","senior","gold",60,75,750000,34000,10,"Single AC",12,30,10,50,True,True,3000,True,False,True,7000,False,True,"1/2","Up to 75","Cosmetic surgery,Dental,Substance abuse,Maternity","Senior 60-75 moderate co-pay restoration benefit"),
  ("SEN-GLD-004","SwiftCare Golden Years — Gold Plus","senior","gold",60,80,1000000,44000,10,"Single private",12,30,10,50,True,True,3500,True,False,True,7500,True,True,"1/2","Up to 80","Cosmetic surgery,Dental,Substance abuse,Maternity","Senior up to 80 10L CI cover gold features"),
  ("SEN-GLD-005","SwiftCare Golden Years — Gold Max","senior","gold",60,80,1500000,56000,10,"Single private",12,30,15,75,True,True,4000,True,False,True,8000,True,True,"1/2","Up to 80","Cosmetic surgery,Dental,Substance abuse,Maternity","Active senior 60-80 high NCB CI teleconsult"),
  ("SEN-PLT-006","SwiftCare Platinum Age — Platinum","senior","platinum",60,80,2000000,72000,0,"No limit",6,30,20,100,True,True,5000,True,False,True,9000,True,True,"1/2","Up to 80","Cosmetic surgery,Dental,Substance abuse,Maternity","Senior wanting 0 percent co-pay 20L shortest PED wait"),
  ("SEN-PLT-007","SwiftCare Platinum Age — Platinum Elite","senior","platinum",60,75,3000000,95000,0,"No limit",6,30,20,100,True,True,7500,True,False,True,10000,True,True,"1/2","Up to 75","Cosmetic surgery,Dental,Substance abuse,Maternity","High-net-worth senior 30L every feature 0 percent co-pay"),
  ("SEN-SLV-008","SwiftCare Red Carpet — Silver","senior","silver",61,70,300000,15500,30,"Shared",6,30,5,25,False,True,1500,True,False,True,5000,False,False,"1","Up to 70","Cosmetic surgery,Dental,Substance abuse,Maternity","Senior with pre-existing conditions lowest premium entry"),
  ("SEN-GLD-009","SwiftCare Cardiac Care — Gold","senior","gold",60,75,1000000,52000,10,"Single private",6,30,10,50,True,True,4000,True,False,True,8000,True,True,"1/2","Up to 75","Cosmetic surgery,Dental,Substance abuse,Maternity","Senior with heart condition short PED wait CI cover"),
  ("SEN-PLT-010","SwiftCare Diabetes Plus — Platinum","senior","platinum",60,75,1500000,68000,0,"Single private",3,30,15,75,True,True,5000,True,False,True,9000,True,True,"1/2","Up to 75","Cosmetic surgery,Dental,Substance abuse,Maternity","Diabetic senior ultra-short 3-month PED wait all-in"),
]

sql = """
INSERT INTO plans (
  plan_id, plan_name, category, tier, min_age, max_age,
  sum_insured, annual_premium_base, co_payment_pct, room_rent_limit,
  ped_waiting_months, initial_waiting_days, no_claim_bonus_pct, max_ncb_pct,
  restoration_benefit, daycare_covered, ambulance_cover, ayush_covered,
  maternity_covered, annual_checkup, network_hospitals, critical_illness_cover,
  teleconsult, policy_tenure_options, renewability, key_exclusions, best_for
) VALUES (
  :plan_id, :plan_name, :category, :tier, :min_age, :max_age,
  :sum_insured, :annual_premium_base, :co_payment_pct, :room_rent_limit,
  :ped_waiting_months, :initial_waiting_days, :no_claim_bonus_pct, :max_ncb_pct,
  :restoration_benefit, :daycare_covered, :ambulance_cover, :ayush_covered,
  :maternity_covered, :annual_checkup, :network_hospitals, :critical_illness_cover,
  :teleconsult, :policy_tenure_options, :renewability, :key_exclusions, :best_for
) ON CONFLICT (plan_id) DO NOTHING
"""

fields = ["plan_id","plan_name","category","tier","min_age","max_age",
          "sum_insured","annual_premium_base","co_payment_pct","room_rent_limit",
          "ped_waiting_months","initial_waiting_days","no_claim_bonus_pct","max_ncb_pct",
          "restoration_benefit","daycare_covered","ambulance_cover","ayush_covered",
          "maternity_covered","annual_checkup","network_hospitals","critical_illness_cover",
          "teleconsult","policy_tenure_options","renewability","key_exclusions","best_for"]

for plan in plans:
    params = []
    for i, field in enumerate(fields):
        val = plan[i]
        if isinstance(val, bool):
            params.append({"name": field, "value": {"booleanValue": val}})
        elif isinstance(val, int):
            params.append({"name": field, "value": {"longValue": val}})
        else:
            params.append({"name": field, "value": {"stringValue": str(val)}})
    execute(sql, database="plandb", params=params)

# Verify
result = execute("SELECT COUNT(*) as cnt FROM plans", database="plandb")
count = result["records"][0][0]["longValue"]
print(f"  ✅ {count} plans seeded in plandb")

print("\n🎉 Database bootstrap complete!")
print("   txndb: users, submissions, transactions, plan_selections, audit_log")
print("   plandb: plans (30 SwiftCare plans seeded)")
