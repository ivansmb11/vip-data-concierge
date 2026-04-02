# VIP Data Concierge - Build Walkthrough

A step-by-step guide to building the entire Zero-Trust AI Agent infrastructure from scratch on Google Cloud Platform.

**Project:** `hstia-agent`
**Region:** `us-central1`
**Time to complete:** ~2 hours

---

## Table of Contents

1. [Project and API Setup](#step-1-project-and-api-setup)
2. [Network Foundation](#step-2-network-foundation)
3. [Connectivity Hub (NCC)](#step-3-connectivity-hub-ncc)
4. [Route Verification](#step-4-route-verification)
5. [Firewall Rules](#step-5-firewall-rules)
6. [Cloud SQL Databases](#step-6-cloud-sql-databases)
7. [Private Service Connect](#step-7-private-service-connect)
8. [Seed Data](#step-8-seed-data)
9. [Agent Logic (Python)](#step-9-agent-logic-python)
10. [Cloud Run Deployment](#step-10-cloud-run-deployment)
11. [Smoke Test](#step-11-smoke-test)
12. [Teardown](#step-12-teardown)

---

## Step 1: Project and API Setup

Set the active project and enable all required APIs.

```bash
gcloud config set project hstia-agent

gcloud services enable \
  compute.googleapis.com \
  networkconnectivity.googleapis.com \
  sqladmin.googleapis.com \
  aiplatform.googleapis.com \
  run.googleapis.com \
  vpcaccess.googleapis.com \
  servicenetworking.googleapis.com \
  iap.googleapis.com \
  iamcredentials.googleapis.com \
  --project=hstia-agent
```

Get your project number and grant IAM roles to the default compute service account:

```bash
PROJECT_NUMBER=$(gcloud projects describe hstia-agent --format="value(projectNumber)")
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for ROLE in \
  roles/compute.networkAdmin \
  roles/networkconnectivity.hubAdmin \
  roles/cloudsql.admin \
  roles/aiplatform.user \
  roles/run.admin \
  roles/vpcaccess.admin \
  roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding hstia-agent \
    --member="serviceAccount:${SA}" \
    --role="${ROLE}" \
    --quiet
done
```

**Verify:**

```bash
gcloud services list --enabled --project=hstia-agent \
  --filter="NAME:(compute OR networkconnectivity OR sqladmin OR aiplatform OR run OR vpcaccess OR servicenetworking OR iap)"
```

Expected: 8 APIs listed.

---

## Step 2: Network Foundation

Create 3 VPCs with custom subnets and Private Google Access enabled.

| VPC | Subnet | CIDR |
|-----|--------|------|
| vpc-hub | subnet-hub | 10.0.0.0/24 |
| vpc-spoke-hr | subnet-hr | 10.1.0.0/24 |
| vpc-spoke-fin | subnet-fin | 10.2.0.0/24 |

```bash
# Hub VPC
gcloud compute networks create vpc-hub \
  --subnet-mode=custom --project=hstia-agent

gcloud compute networks subnets create subnet-hub \
  --network=vpc-hub --range=10.0.0.0/24 --region=us-central1 \
  --enable-private-ip-google-access --project=hstia-agent

# HR Spoke VPC
gcloud compute networks create vpc-spoke-hr \
  --subnet-mode=custom --project=hstia-agent

gcloud compute networks subnets create subnet-hr \
  --network=vpc-spoke-hr --range=10.1.0.0/24 --region=us-central1 \
  --enable-private-ip-google-access --project=hstia-agent

# Finance Spoke VPC
gcloud compute networks create vpc-spoke-fin \
  --subnet-mode=custom --project=hstia-agent

gcloud compute networks subnets create subnet-fin \
  --network=vpc-spoke-fin --range=10.2.0.0/24 --region=us-central1 \
  --enable-private-ip-google-access --project=hstia-agent
```

**Verify:**

```bash
gcloud compute networks list --project=hstia-agent
gcloud compute networks subnets list --project=hstia-agent --filter="region:us-central1"
```

---

## Step 3: Connectivity Hub (NCC)

Create the Network Connectivity Center hub and attach all 3 VPCs as spokes. NCC automatically exchanges routes between spokes via BGP.

```bash
# Create the hub
gcloud network-connectivity hubs create ncc-hub \
  --project=hstia-agent \
  --description="VIP Data Concierge - Hub for spoke VPCs"

# Attach all 3 VPCs as spokes
gcloud network-connectivity spokes linked-vpc-network create spoke-hub \
  --hub=ncc-hub --vpc-network=vpc-hub --global --project=hstia-agent

gcloud network-connectivity spokes linked-vpc-network create spoke-hr \
  --hub=ncc-hub --vpc-network=vpc-spoke-hr --global --project=hstia-agent

gcloud network-connectivity spokes linked-vpc-network create spoke-fin \
  --hub=ncc-hub --vpc-network=vpc-spoke-fin --global --project=hstia-agent
```

**Verify:**

```bash
gcloud network-connectivity spokes list --project=hstia-agent
```

Expected: 3 spokes, all with `TYPE: VPC network`.

---

## Step 4: Route Verification

Confirm that NCC injected routes so the Hub can reach both spoke subnets.

```bash
gcloud compute routes list \
  --project=hstia-agent \
  --filter="network:vpc-hub" \
  --format="table(name, destRange, nextHopHub, priority)"
```

Expected routes in vpc-hub:
- `10.0.0.0/24` - local subnet (direct)
- `10.1.0.0/24` - via ncc-hub (NCC injected)
- `10.2.0.0/24` - via ncc-hub (NCC injected)

> **Note:** NCC exchanges subnet routes between spokes, but does NOT propagate Cloud SQL private service networking ranges (e.g., 10.1.1.0/24). This is why we need PSC in Step 7.

---

## Step 5: Firewall Rules

Allow internal traffic between Hub and Spokes. Block all internet ingress. Spokes can only talk to the Hub, never to each other.

```bash
# Hub: allow inbound from both spokes
gcloud compute firewall-rules create hub-allow-spokes \
  --network=vpc-hub --direction=INGRESS --action=ALLOW \
  --rules=tcp,udp,icmp --source-ranges=10.1.0.0/24,10.2.0.0/24 \
  --priority=1000 --project=hstia-agent

# HR Spoke: allow inbound from Hub only
gcloud compute firewall-rules create hr-allow-hub \
  --network=vpc-spoke-hr --direction=INGRESS --action=ALLOW \
  --rules=tcp,udp,icmp --source-ranges=10.0.0.0/24 \
  --priority=1000 --project=hstia-agent

# Finance Spoke: allow inbound from Hub only
gcloud compute firewall-rules create fin-allow-hub \
  --network=vpc-spoke-fin --direction=INGRESS --action=ALLOW \
  --rules=tcp,udp,icmp --source-ranges=10.0.0.0/24 \
  --priority=1000 --project=hstia-agent

# Block all internet ingress on all 3 VPCs
for VPC in vpc-hub vpc-spoke-hr vpc-spoke-fin; do
  gcloud compute firewall-rules create ${VPC}-deny-internet \
    --network=${VPC} --direction=INGRESS --action=DENY \
    --rules=all --source-ranges=0.0.0.0/0 \
    --priority=65534 --project=hstia-agent
done
```

**Traffic matrix:**

```
            To Hub    To HR     To Fin    To Internet
From Hub      -        yes       yes       blocked
From HR      yes       -         blocked   blocked
From Fin     yes       blocked   -         blocked
From Internet blocked  blocked   blocked   -
```

**Verify:**

```bash
gcloud compute firewall-rules list \
  --project=hstia-agent \
  --filter="network:(vpc-hub OR vpc-spoke-hr OR vpc-spoke-fin)" \
  --format="table(name, network, sourceRanges)"
```

Expected: 6 rules.

---

## Step 6: Cloud SQL Databases

Create two PostgreSQL 15 instances with private IP only (no public IP). Each lives in its own spoke VPC.

### 6A: Allocate private IP ranges for Cloud SQL

```bash
gcloud compute addresses create sql-range-hr \
  --global --purpose=VPC_PEERING --addresses=10.1.1.0 \
  --prefix-length=24 --network=vpc-spoke-hr --project=hstia-agent

gcloud compute addresses create sql-range-fin \
  --global --purpose=VPC_PEERING --addresses=10.2.1.0 \
  --prefix-length=24 --network=vpc-spoke-fin --project=hstia-agent
```

### 6B: Create private service connections

```bash
gcloud services vpc-peerings connect \
  --service=servicenetworking.googleapis.com \
  --ranges=sql-range-hr --network=vpc-spoke-hr --project=hstia-agent

gcloud services vpc-peerings connect \
  --service=servicenetworking.googleapis.com \
  --ranges=sql-range-fin --network=vpc-spoke-fin --project=hstia-agent
```

### 6C: Create PostgreSQL instances

> Takes 5-10 minutes each. Run in parallel using two terminal tabs.

```bash
# Tab 1
gcloud sql instances create db-hr \
  --database-version=POSTGRES_15 --tier=db-f1-micro \
  --region=us-central1 --network=vpc-spoke-hr \
  --no-assign-ip --project=hstia-agent

# Tab 2
gcloud sql instances create db-fin \
  --database-version=POSTGRES_15 --tier=db-f1-micro \
  --region=us-central1 --network=vpc-spoke-fin \
  --no-assign-ip --project=hstia-agent
```

### 6D: Set passwords

```bash
gcloud sql users set-password postgres \
  --instance=db-hr --password=hr-secret-2024 --project=hstia-agent

gcloud sql users set-password postgres \
  --instance=db-fin --password=fin-secret-2024 --project=hstia-agent
```

### 6E: Create application databases

```bash
gcloud sql databases create hr_data --instance=db-hr --project=hstia-agent
gcloud sql databases create fin_data --instance=db-fin --project=hstia-agent
```

**Verify:**

```bash
gcloud sql instances list --project=hstia-agent \
  --format="table(name, region, settings.ipConfiguration.privateNetwork, ipAddresses)"
```

Expected: Both instances with private IPs only (e.g., `10.1.1.3` and `10.2.1.3`).

---

## Step 7: Private Service Connect

Cloud SQL private IPs live inside Google's service networking peering, which NCC does not propagate. PSC creates local endpoints in the Hub that tunnel to each database.

### 7A: Enable PSC on both Cloud SQL instances

```bash
gcloud sql instances patch db-hr \
  --enable-private-service-connect \
  --allowed-psc-projects=hstia-agent --project=hstia-agent

gcloud sql instances patch db-fin \
  --enable-private-service-connect \
  --allowed-psc-projects=hstia-agent --project=hstia-agent
```

### 7B: Get the PSC service attachment URIs

```bash
gcloud sql instances describe db-hr \
  --project=hstia-agent --format="value(pscServiceAttachmentLink)"

gcloud sql instances describe db-fin \
  --project=hstia-agent --format="value(pscServiceAttachmentLink)"
```

Save these URIs, you'll need them in the next step.

### 7C: Create PSC endpoints in the Hub

Replace `<HR_ATTACHMENT>` and `<FIN_ATTACHMENT>` with the URIs from 7B.

```bash
# Reserve static IPs
gcloud compute addresses create psc-ip-hr \
  --subnet=subnet-hub --addresses=10.0.0.50 \
  --region=us-central1 --project=hstia-agent

gcloud compute addresses create psc-ip-fin \
  --subnet=subnet-hub --addresses=10.0.0.51 \
  --region=us-central1 --project=hstia-agent

# Create forwarding rules
gcloud compute forwarding-rules create psc-endpoint-hr \
  --region=us-central1 --network=vpc-hub --address=psc-ip-hr \
  --target-service-attachment=<HR_ATTACHMENT> --project=hstia-agent

gcloud compute forwarding-rules create psc-endpoint-fin \
  --region=us-central1 --network=vpc-hub --address=psc-ip-fin \
  --target-service-attachment=<FIN_ATTACHMENT> --project=hstia-agent
```

**Verify:**

```bash
gcloud compute forwarding-rules list \
  --project=hstia-agent --filter="region:us-central1" \
  --format="table(name, IPAddress, target)"
```

Expected:
- `psc-endpoint-hr` at `10.0.0.50`
- `psc-endpoint-fin` at `10.0.0.51`

---

## Step 8: Seed Data

We need a VM inside the Hub VPC to reach the PSC endpoints and seed the databases. Cloud Shell cannot reach private IPs.

### 8A: Create a temporary seed VM

```bash
gcloud compute instances create seed-vm \
  --zone=us-central1-a --machine-type=e2-micro \
  --subnet=subnet-hub --no-address \
  --scopes=sql-admin --project=hstia-agent

# Allow IAP SSH access
gcloud compute firewall-rules create hub-allow-iap-ssh \
  --network=vpc-hub --direction=INGRESS --action=ALLOW \
  --rules=tcp:22 --source-ranges=35.235.240.0/20 \
  --priority=900 --project=hstia-agent
```

### 8B: Add Cloud NAT for package downloads

The VM has no public IP, so it cannot download packages. Cloud NAT provides outbound internet:

```bash
gcloud compute routers create hub-router \
  --network=vpc-hub --region=us-central1 --project=hstia-agent

gcloud compute routers nats create hub-nat \
  --router=hub-router --region=us-central1 \
  --auto-allocate-nat-external-ips \
  --nat-all-subnet-ip-ranges --project=hstia-agent
```

### 8C: SSH in and install PostgreSQL client

```bash
gcloud compute ssh seed-vm \
  --zone=us-central1-a --project=hstia-agent --tunnel-through-iap
```

Inside the VM:

```bash
sudo apt-get update -qq && sudo apt-get install -y -qq postgresql-client
```

### 8D: Seed HR database

```bash
PGPASSWORD=hr-secret-2024 psql -h 10.0.0.50 -p 5432 -U postgres -d hr_data <<'SQL'
CREATE TABLE employees (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  department VARCHAR(50) NOT NULL,
  position VARCHAR(100) NOT NULL,
  salary NUMERIC(12,2) NOT NULL,
  hire_date DATE NOT NULL
);

INSERT INTO employees (name, department, position, salary, hire_date) VALUES
  ('Ana Garcia', 'Engineering', 'Senior Developer', 95000.00, '2021-03-15'),
  ('Carlos Lopez', 'Engineering', 'Tech Lead', 120000.00, '2019-07-01'),
  ('Maria Rodriguez', 'Marketing', 'Marketing Manager', 85000.00, '2020-11-10'),
  ('Juan Hernandez', 'HR', 'HR Director', 110000.00, '2018-01-20'),
  ('Laura Martinez', 'Engineering', 'Junior Developer', 65000.00, '2023-06-01'),
  ('Pedro Sanchez', 'Sales', 'Sales Lead', 90000.00, '2020-04-15'),
  ('Sofia Torres', 'Marketing', 'Content Specialist', 70000.00, '2022-09-01'),
  ('Diego Ramirez', 'Engineering', 'DevOps Engineer', 100000.00, '2021-01-10');

SELECT 'HR seed complete: ' || count(*) || ' employees' FROM employees;
SQL
```

### 8E: Seed Finance database

```bash
PGPASSWORD=fin-secret-2024 psql -h 10.0.0.51 -p 5432 -U postgres -d fin_data <<'SQL'
CREATE TABLE invoices (
  id SERIAL PRIMARY KEY,
  vendor VARCHAR(100) NOT NULL,
  amount NUMERIC(12,2) NOT NULL,
  status VARCHAR(20) NOT NULL,
  due_date DATE NOT NULL,
  department VARCHAR(50) NOT NULL
);

CREATE TABLE budgets (
  id SERIAL PRIMARY KEY,
  department VARCHAR(50) NOT NULL,
  quarter VARCHAR(10) NOT NULL,
  allocated NUMERIC(12,2) NOT NULL,
  spent NUMERIC(12,2) NOT NULL
);

INSERT INTO invoices (vendor, amount, status, due_date, department) VALUES
  ('AWS', 45000.00, 'paid', '2024-01-15', 'Engineering'),
  ('Google Cloud', 32000.00, 'pending', '2024-02-28', 'Engineering'),
  ('HubSpot', 12000.00, 'paid', '2024-01-30', 'Marketing'),
  ('Salesforce', 28000.00, 'overdue', '2024-01-10', 'Sales'),
  ('Adobe', 8500.00, 'pending', '2024-03-15', 'Marketing'),
  ('DataDog', 15000.00, 'paid', '2024-02-01', 'Engineering'),
  ('Slack', 6000.00, 'paid', '2024-01-20', 'HR'),
  ('WeWork', 50000.00, 'pending', '2024-03-01', 'Operations');

INSERT INTO budgets (department, quarter, allocated, spent) VALUES
  ('Engineering', 'Q1-2024', 200000.00, 92000.00),
  ('Marketing', 'Q1-2024', 80000.00, 20500.00),
  ('Sales', 'Q1-2024', 60000.00, 28000.00),
  ('HR', 'Q1-2024', 40000.00, 6000.00),
  ('Operations', 'Q1-2024', 100000.00, 50000.00);

SELECT 'Finance seed complete: ' || count(*) || ' invoices, ' ||
       (SELECT count(*) FROM budgets) || ' budgets' FROM invoices;
SQL
```

### 8F: Clean up seed infrastructure

Exit the VM and remove everything we created for seeding:

```bash
exit

gcloud compute instances delete seed-vm \
  --zone=us-central1-a --project=hstia-agent --quiet

gcloud compute routers nats delete hub-nat \
  --router=hub-router --region=us-central1 --project=hstia-agent --quiet

gcloud compute routers delete hub-router \
  --region=us-central1 --project=hstia-agent --quiet

gcloud compute firewall-rules delete hub-allow-iap-ssh \
  --project=hstia-agent --quiet
```

---

## Step 9: Agent Logic (Python)

The agent is a Flask app that:
1. Extracts user identity from request headers
2. Maps the user to a department (HR or Finance)
3. Creates a Gemini agent with only that department's tools
4. Executes the tool against the correct PSC endpoint
5. Returns the formatted answer

### Project structure

```
├── app.py              # Flask server, identity extraction, routing
├── agent.py            # Gemini agent with Function Calling loop
├── tools.py            # LangChain tools (3 HR + 3 Finance)
├── db.py               # Database access layer via PSC endpoints
├── config.py           # Environment-based configuration
├── Dockerfile          # Container for Cloud Run
└── requirements.txt    # Python dependencies
```

### Key files

**config.py** - Maps departments to PSC endpoint IPs via environment variables:
- HR: `10.0.0.50`
- Finance: `10.0.0.51`

**tools.py** - 6 LangChain tools, 3 per department:
- HR: `list_employees`, `search_employee`, `get_department_salary_summary`
- Finance: `list_invoices`, `get_budget_summary`, `get_overdue_invoices`

**agent.py** - Security enforcement:
- Forces the `department` parameter on every tool call
- HR users can only invoke HR tools
- Finance users can only invoke Finance tools

**app.py** - Identity layer:
- Reads `X-Goog-Authenticated-User-Email` (IAP header) or `X-User-Email` (testing)
- Unmapped users get 401

See the source code in this repository for full implementation.

---

## Step 10: Cloud Run Deployment

### 10A: Create VPC connector

Cloud Run needs a Serverless VPC Access connector to reach the Hub VPC:

```bash
gcloud compute networks vpc-access connectors create hub-connector \
  --region=us-central1 --network=vpc-hub \
  --range=10.0.1.0/28 --project=hstia-agent
```

### 10B: Create Artifact Registry

```bash
gcloud artifacts repositories create cloud-run-source-deploy \
  --repository-format=docker --location=us-central1 --project=hstia-agent
```

### 10C: Set up Workload Identity Federation for GitHub Actions

```bash
# Service account
gcloud iam service-accounts create github-deploy \
  --display-name="GitHub Actions Deploy" --project=hstia-agent

SA="github-deploy@hstia-agent.iam.gserviceaccount.com"

for ROLE in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding hstia-agent \
    --member="serviceAccount:${SA}" --role="${ROLE}" --quiet
done

# Workload Identity Pool
gcloud iam workload-identity-pools create github-pool \
  --location=global --display-name="GitHub Actions Pool" --project=hstia-agent

# OIDC Provider (replace OWNER/REPO with your GitHub repo)
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global --workload-identity-pool=github-pool \
  --display-name="GitHub Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='OWNER/REPO'" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --project=hstia-agent

# Allow repo to impersonate the service account
PROJECT_NUMBER=$(gcloud projects describe hstia-agent --format="value(projectNumber)")

gcloud iam service-accounts add-iam-policy-binding ${SA} \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/OWNER/REPO" \
  --project=hstia-agent

# Get the provider name for GitHub secrets
gcloud iam workload-identity-pools providers describe github-provider \
  --location=global --workload-identity-pool=github-pool \
  --project=hstia-agent --format="value(name)"
```

### 10D: Set GitHub secrets

```bash
gh secret set WIF_PROVIDER --repo=OWNER/REPO \
  --body="projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/providers/github-provider"

gh secret set WIF_SERVICE_ACCOUNT --repo=OWNER/REPO \
  --body="github-deploy@hstia-agent.iam.gserviceaccount.com"

gh secret set HR_DB_PASSWORD --repo=OWNER/REPO --body="hr-secret-2024"
gh secret set FIN_DB_PASSWORD --repo=OWNER/REPO --body="fin-secret-2024"
```

### 10E: Deploy

Push to master triggers the GitHub Actions pipeline, or deploy manually:

```bash
gcloud run deploy vip-concierge \
  --source=. --region=us-central1 \
  --vpc-connector=hub-connector \
  --vpc-egress=private-ranges-only \
  --allow-unauthenticated \
  --memory=512Mi --timeout=120 \
  --set-env-vars="HR_DB_PASSWORD=hr-secret-2024,FIN_DB_PASSWORD=fin-secret-2024" \
  --project=hstia-agent
```

### 10F: Allow public access

```bash
gcloud run services add-iam-policy-binding vip-concierge \
  --region=us-central1 --member="allUsers" \
  --role="roles/run.invoker" --project=hstia-agent
```

### 10G: Enable Vertex AI models

Visit Vertex AI Studio in the console to accept terms:

```
https://console.cloud.google.com/vertex-ai/studio/multimodal?project=hstia-agent
```

> **Important:** The `--vpc-egress=private-ranges-only` setting is critical. Using `all-traffic` routes Vertex AI API calls through the VPC which has no internet, causing model requests to fail.

---

## Step 11: Smoke Test

Get the service URL and test all 3 scenarios:

```bash
SERVICE_URL=$(gcloud run services describe vip-concierge \
  --region=us-central1 --project=hstia-agent --format="value(status.url)")
```

### Test 1: HR user queries employees

```bash
curl -s -X POST "${SERVICE_URL}/query" \
  -H "Content-Type: application/json" \
  -H "X-User-Email: hr@example.com" \
  -d '{"question": "List all employees"}' | python3 -m json.tool
```

Expected: Returns 8 employees from the HR database.

### Test 2: Finance user queries invoices

```bash
curl -s -X POST "${SERVICE_URL}/query" \
  -H "Content-Type: application/json" \
  -H "X-User-Email: finance@example.com" \
  -d '{"question": "Show me all overdue invoices"}' | python3 -m json.tool
```

Expected: Returns Salesforce $28,000 overdue invoice.

### Test 3: Finance user tries to access HR data

```bash
curl -s -X POST "${SERVICE_URL}/query" \
  -H "Content-Type: application/json" \
  -H "X-User-Email: finance@example.com" \
  -d '{"question": "List all employees"}' | python3 -m json.tool
```

Expected: Agent refuses, saying it cannot access employee data.

### Test 4: Unauthorized user

```bash
curl -s -X POST "${SERVICE_URL}/query" \
  -H "Content-Type: application/json" \
  -H "X-User-Email: hacker@evil.com" \
  -d '{"question": "List all employees"}' | python3 -m json.tool
```

Expected: 401 error, user not mapped to any department.

---

## Step 12: Teardown

### Option A: Delete individual resources

```bash
# Cloud Run
gcloud run services delete vip-concierge --region=us-central1 --project=hstia-agent --quiet

# VPC connector
gcloud compute networks vpc-access connectors delete hub-connector \
  --region=us-central1 --project=hstia-agent --quiet

# Cloud SQL
gcloud sql instances delete db-hr --project=hstia-agent --quiet
gcloud sql instances delete db-fin --project=hstia-agent --quiet

# PSC endpoints
gcloud compute forwarding-rules delete psc-endpoint-hr psc-endpoint-fin \
  --region=us-central1 --project=hstia-agent --quiet
gcloud compute addresses delete psc-ip-hr psc-ip-fin \
  --region=us-central1 --project=hstia-agent --quiet

# NCC
gcloud network-connectivity spokes delete spoke-hub spoke-hr spoke-fin \
  --global --project=hstia-agent --quiet
gcloud network-connectivity hubs delete ncc-hub --project=hstia-agent --quiet

# Firewall rules
gcloud compute firewall-rules delete hub-allow-spokes hr-allow-hub fin-allow-hub \
  vpc-hub-deny-internet vpc-spoke-hr-deny-internet vpc-spoke-fin-deny-internet \
  --project=hstia-agent --quiet

# Service networking
gcloud compute addresses delete sql-range-hr sql-range-fin \
  --global --project=hstia-agent --quiet

# Subnets
gcloud compute networks subnets delete subnet-hub subnet-hr subnet-fin \
  --region=us-central1 --project=hstia-agent --quiet

# VPCs
gcloud compute networks delete vpc-hub vpc-spoke-hr vpc-spoke-fin \
  --project=hstia-agent --quiet
```

### Option B: Delete the entire project

```bash
gcloud projects delete hstia-agent
```

---

## Lessons Learned

1. **NCC does not propagate service networking ranges.** Subnet routes (10.x.0.0/24) are exchanged, but Cloud SQL peering ranges (10.x.1.0/24) are not. PSC is required.

2. **VPC egress matters on Cloud Run.** `--vpc-egress=all-traffic` breaks Vertex AI calls because the VPC has no internet. Use `private-ranges-only` so database traffic goes through the VPC while API calls go directly to Google.

3. **Vertex AI models require console activation.** Even with the API enabled, you must visit Vertex AI Studio and accept terms before the models become accessible.

4. **Cloud NAT is needed for private VMs.** VMs without public IPs cannot download packages. Create Cloud NAT temporarily, then remove it after seeding.

5. **IAP SSH needs a firewall rule.** The deny-all-internet rule blocks IAP's IP range (35.235.240.0/20). Add a higher-priority allow rule for TCP:22 from that range.
