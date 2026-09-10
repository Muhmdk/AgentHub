# Azure model and search adapters

AgentHub keeps Azure at the provider boundary. Agents continue to depend on the
provider-neutral `ChatModel` and `Retriever` contracts, while local development remains
deterministic and offline by default.

## Runtime selection

Set only the provider you intend to use. There is no automatic cloud fallback.

| Setting | Local default | Azure value |
| --- | --- | --- |
| `AGENTHUB_MODEL_PROVIDER` | `fake` | `azure-openai` |
| `AGENTHUB_RETRIEVAL_PROVIDER` | `local` | `azure-search` |
| `AGENTHUB_AZURE_MANAGED_IDENTITY_CLIENT_ID` | unset | workload identity client ID |
| `AGENTHUB_AZURE_OPENAI_ENDPOINT` | unset | `https://<account>.openai.azure.com` |
| `AGENTHUB_AZURE_OPENAI_DEPLOYMENT` | unset | existing deployment name |
| `AGENTHUB_AZURE_SEARCH_ENDPOINT` | unset | Terraform `platform.search.endpoint` output |
| `AGENTHUB_AZURE_SEARCH_INDEX_NAME` | unset | existing index name |
| `AGENTHUB_DATABASE_AUTH_MODE` | `password` | set to `azure-workload-identity` on AKS |
| `AGENTHUB_AZURE_POSTGRES_TOKEN_SCOPE` | Azure PostgreSQL scope | token audience for passwordless database connections |
| `AGENTHUB_OTEL_EXPORTER` | `otlp` | set to `azure-monitor` in the dev chart |
| `AGENTHUB_AZURE_MONITOR_CONNECTION_STRING` | unset | Application Insights routing coordinates loaded from Key Vault |

`DefaultAzureCredential` acquires Entra tokens. In AKS, the `agenthub` service account must
carry the workload identity label and client-ID annotation described by the Helm chart. Local
Azure testing may use an existing Azure CLI login. The model and Search adapters do not accept API
keys; Azure Monitor uses its connection string only for routing and uses Entra for authentication.

The Azure OpenAI adapter calls the OpenAI-compatible
`/openai/v1/chat/completions` route. Its default token scope is
`https://cognitiveservices.azure.com/.default`. A Foundry resource that requires the
`https://ai.azure.com/.default` audience can override
`AGENTHUB_AZURE_OPENAI_TOKEN_SCOPE` explicitly.

The Search adapter uses the stable `2026-04-01` data-plane API and the
`https://search.azure.com/.default` scope. Requests always filter by corpus ID and immutable
corpus version before applying caller metadata filters.

## Model quota and deployment

The Terraform stack intentionally does not create a model account or deployment. Model access,
regional availability, deployment types, versions, and quota are subscription-dependent and
can add usage charges that are not part of the fixed infrastructure estimate.

Before enabling `azure-openai`:

1. Obtain approval for the chosen model, region, deployment type, quota, and token budget.
2. Create or select the Azure OpenAI/Foundry account and deploy the approved model.
3. Set `azure_openai_resource_id` in the environment Terraform variables. The platform module
   grants the AgentHub workload identity the bounded `Cognitive Services OpenAI User` role.
4. Set the endpoint, deployment name, and input/output cost rates in the runtime environment.
   The rates default to zero because model pricing varies; a zero estimate must not be treated as
   free usage.
5. Run the post-deployment smoke checks before directing user traffic to the Azure provider.

Do not substitute a broader Contributor role when inference-only access is sufficient. If a
Foundry project uses a different data-plane role, review and assign that role at the narrowest
project or account scope outside this module.

## Search index contract

Terraform creates the Basic Search service, disables local-key authentication, restricts its
public network path to the static AKS egress address, and grants the workload identity
`Search Index Data Reader`. Index lifecycle and document ingestion are separate from the
application's read-only identity.

Create an index with these fields before selecting `azure-search`:

| Field | Azure type | Required behavior |
| --- | --- | --- |
| `chunk_id` | `Edm.String` | key, retrievable |
| `document_id` | `Edm.String` | filterable, retrievable |
| `document_title` | `Edm.String` | searchable, retrievable |
| `content` | `Edm.String` | searchable, retrievable |
| `content_hash` | `Edm.String` | filterable, retrievable |
| `chunk_index` | `Edm.Int32` | sortable, retrievable |
| `corpus_id` | `Edm.String` | filterable, retrievable |
| `corpus_version` | `Edm.String` | filterable, retrievable |
| `metadata` | `Edm.ComplexType` | retrievable; declared scalar children must be filterable |

The committed retail fixture currently uses the metadata children `category`, `kind`, `name`,
`price`, `sku`, `source`, `topic`, and `trusted`. Declare the string, number, and Boolean child
types to match the source values. Azure Search schemas do not accept undeclared dynamic complex
children.

Use an approved operator group's short-lived Entra session with `Search Service Contributor` and
`Search Index Data Contributor` to create the index and upload chunks from a reviewed operator
CIDR. Do not grant document write access to the application service account. The upload must preserve the committed
`retail-products-policies` / `v1` corpus coordinates and chunk hashes so retrieval evidence stays
reproducible.

## Failure and privacy behavior

- HTTP, token, and response-validation failures are converted to short provider errors that do
  not include prompts, bearer tokens, response bodies, endpoints, or index queries.
- Selecting an Azure provider with incomplete settings stops configuration validation; it never
  falls back to the fake model or local corpus.
- The shared credential is closed during API shutdown and after each CLI invocation.
- No live Azure calls are made by unit tests. Tests inject recording token and HTTP boundaries.

## PostgreSQL and Azure Monitor adapters

The dev database URL contains the workload identity name but no password. SQLAlchemy requests a
fresh Entra token for every new DBAPI connection and passes that token only as the PostgreSQL
password. A pre-install Helm hook uses a separate federated administrator identity to create or
reuse the workload principal, run migrations, and grant connection plus DML permissions. The API
identity is never a PostgreSQL administrator.

Local telemetry continues to use OTLP/HTTP. The dev profile selects the Azure Monitor trace and
metric exporters, uses the same workload identity for Entra authentication, and disables exporter
disk storage for the chart's read-only filesystem. The Application Insights connection string
provides routing coordinates and is mounted from Key Vault rather than committed or passed through
Terraform variables.

## References

- [Azure OpenAI v1 REST API](https://learn.microsoft.com/en-us/azure/foundry/openai/latest)
- [Authenticate Azure OpenAI with Microsoft Entra ID](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/managed-identity)
- [Azure AI Search document search API](https://learn.microsoft.com/en-us/rest/api/searchservice/documents/search-post)
- [Azure AI Search role-based access](https://learn.microsoft.com/en-us/azure/search/search-security-rbac)
- [Azure workload identity on AKS](https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview)
