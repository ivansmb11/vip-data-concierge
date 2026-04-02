# VIP Data Concierge

A Zero-Trust AI Agent that routes queries to isolated databases based on user identity. Built on GCP with Hub-and-Spoke networking, Private Service Connect, and Vertex AI.

[![Demo Video](https://img.youtube.com/vi/3ATSpNSdtiw/maxresdefault.jpg)](https://youtu.be/3ATSpNSdtiw)

## Architecture

```
                     User / Internet
                          |
                     [ IAP ]
                          |
    ┌─────────────────────┴─────────────────────────┐
    |              vpc-hub  10.0.0.0/24              |
    |                                                |
    |            [ Cloud Run Agent ]                 |
    |          Gemini 2.5 Flash + LangChain          |
    |                                                |
    |   [ PSC 10.0.0.50 ]    [ PSC 10.0.0.51 ]     |
    └────────┬────────────────────────┬──────────────┘
             |  PSC tunnel            |  PSC tunnel
    ┌────────▼──────────┐   ┌────────▼──────────┐
    | vpc-spoke-hr      |   | vpc-spoke-fin     |
    | 10.1.0.0/24       |   | 10.2.0.0/24       |
    |                   |   |                    |
    | Cloud SQL (HR)    | X | Cloud SQL (Fin)    |
    | PostgreSQL 15     |   | PostgreSQL 15      |
    | 10.1.1.3          |   | 10.2.1.3           |
    └───────────────────┘   └────────────────────┘
         No direct path between spokes

    [ VPC Service Controls Perimeter ]
```

### Key Components

| Component | Purpose |
|-----------|---------|
| **NCC Hub** | Routes traffic between VPCs without peering mesh |
| **PSC Endpoints** | Agent uses Hub-local IPs to reach spoke databases |
| **Private Google Access** | Vertex AI calls stay on Google's backbone |
| **VPC-SC Perimeter** | Prevents data exfiltration outside the project |
| **IAP** | Zero-trust entry, identity determines access |

## How It Works

1. User sends a question via HTTPS to Cloud Run in the Hub VPC
2. IAP verifies identity, attaches email and department claim
3. Agent resolves department (HR or Finance) from identity
4. Gemini picks a tool via Function Calling based on the question
5. Tool queries the correct database through PSC endpoint
6. Gemini formats the final answer from tool results

### Data Isolation

- **HR users** only get HR tools, which only connect to `10.0.0.50` (HR database)
- **Finance users** only get Finance tools, which only connect to `10.0.0.51` (Finance database)
- **Unknown users** are rejected with 401 before any tool is loaded
- Spokes cannot communicate with each other directly

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | Google Cloud NCC |
| Compute | Cloud Run (serverless) |
| Database | Cloud SQL PostgreSQL 15 (private IP only) |
| AI Model | Vertex AI Gemini 2.5 Flash |
| Framework | LangChain + Function Calling |
| Security | IAP, VPC-SC, PSC, IAM |
| CI/CD | GitHub Actions + Workload Identity Federation |

## Project Structure

```
├── app.py              # Flask server, extracts identity, routes to agent
├── agent.py            # Gemini agent with Function Calling loop
├── tools.py            # LangChain tools (HR tools + Finance tools)
├── db.py               # Database access layer via PSC endpoints
├── config.py           # Environment-based configuration
├── Dockerfile          # Container image for Cloud Run
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
└── .github/workflows/
    └── deploy.yml      # CI/CD pipeline with WIF auth
```

## Setup

### Prerequisites

- GCP project with billing enabled
- APIs enabled: Compute, NCC, SQL Admin, Vertex AI, Cloud Run, VPC Access, Service Networking, IAP

### Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

### Deploy

Push to `master` triggers the GitHub Actions pipeline which:

1. Builds the Docker image
2. Pushes to Artifact Registry
3. Deploys to Cloud Run with VPC connector

### Cost Management

Stop the databases when not in use:

```bash
gcloud sql instances patch db-hr --activation-policy=NEVER --project=hstia-agent
gcloud sql instances patch db-fin --activation-policy=NEVER --project=hstia-agent
```

Restart when needed:

```bash
gcloud sql instances patch db-hr --activation-policy=ALWAYS --project=hstia-agent
gcloud sql instances patch db-fin --activation-policy=ALWAYS --project=hstia-agent
```

## Teardown

Delete all infrastructure to stop billing:

```bash
# Delete Cloud Run service
gcloud run services delete vip-concierge --region=us-central1 --project=hstia-agent --quiet

# Delete VPC connector
gcloud compute networks vpc-access connectors delete hub-connector --region=us-central1 --project=hstia-agent --quiet

# Delete Cloud SQL instances
gcloud sql instances delete db-hr --project=hstia-agent --quiet
gcloud sql instances delete db-fin --project=hstia-agent --quiet

# Delete PSC forwarding rules
gcloud compute forwarding-rules delete psc-endpoint-hr --region=us-central1 --project=hstia-agent --quiet
gcloud compute forwarding-rules delete psc-endpoint-fin --region=us-central1 --project=hstia-agent --quiet

# Delete reserved IPs
gcloud compute addresses delete psc-ip-hr --region=us-central1 --project=hstia-agent --quiet
gcloud compute addresses delete psc-ip-fin --region=us-central1 --project=hstia-agent --quiet

# Delete NCC spokes and hub
gcloud network-connectivity spokes delete spoke-hub --global --project=hstia-agent --quiet
gcloud network-connectivity spokes delete spoke-hr --global --project=hstia-agent --quiet
gcloud network-connectivity spokes delete spoke-fin --global --project=hstia-agent --quiet
gcloud network-connectivity hubs delete ncc-hub --project=hstia-agent --quiet

# Delete firewall rules
gcloud compute firewall-rules delete hub-allow-spokes hr-allow-hub fin-allow-hub \
  vpc-hub-deny-internet vpc-spoke-hr-deny-internet vpc-spoke-fin-deny-internet \
  --project=hstia-agent --quiet

# Delete service networking peerings
gcloud compute addresses delete sql-range-hr sql-range-fin --global --project=hstia-agent --quiet

# Delete subnets
gcloud compute networks subnets delete subnet-hub --region=us-central1 --project=hstia-agent --quiet
gcloud compute networks subnets delete subnet-hr --region=us-central1 --project=hstia-agent --quiet
gcloud compute networks subnets delete subnet-fin --region=us-central1 --project=hstia-agent --quiet

# Delete VPCs
gcloud compute networks delete vpc-hub --project=hstia-agent --quiet
gcloud compute networks delete vpc-spoke-hr --project=hstia-agent --quiet
gcloud compute networks delete vpc-spoke-fin --project=hstia-agent --quiet
```

Or delete the entire project:

```bash
gcloud projects delete hstia-agent
```

## Firewall Rules

```
            → Hub     → HR      → Fin     → Internet
From Hub      -        ✅        ✅        ❌
From HR      ✅        -         ❌        ❌
From Fin     ✅        ❌        -         ❌
From Internet ❌       ❌        ❌        -
```

## License

MIT
