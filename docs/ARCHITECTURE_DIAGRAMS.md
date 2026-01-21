# System Architecture Evolution

## 1. Current Architecture (MVP / Single Node)

Designed for: Proof of Concept, Single User, Local Lab.

```mermaid
graph TD
    User((User)) -->|Browser| UI[NiceGUI Web Interface]
    
    subgraph "Single Monolithic Process (Python)"
        UI --> Agent[LangGraph Agent]
        Agent <--> LLM[Ollama (Local)]
        Agent <--> DB[(Postgres / pgvector)]
        Agent --> SSH[SSH Client]
    end
    
    SSH -->|Port 22| Server1[Lab Server 1]
    SSH -->|Port 22| Server2[Lab Server 2]
    SSH -->|Port 22| ServerN[Lab Server N]

    style UI fill:#e1f5fe,stroke:#01579b
    style Agent fill:#fff9c4,stroke:#fbc02d
    style DB fill:#e8f5e9,stroke:#2e7d32
```

**Limitations:**

* **Scale:** UI freezes if Agent is busy.
* **Security:** Requires direct SSH access from the app server to target nodes.
* **Tenancy:** Everyone shares the same database and settings.

---

## 2. Target Scalable Architecture (Enterprise / SaaS)

Designed for: 10,000+ Nodes, Multiple Customers, High Availability.

```mermaid
graph TD
    User((User)) -->|HTTPS| LB[Load Balancer]
    ExtSys[External Systems\nJira / Slack] -->|API| API_GW
    
    LB --> FE[Frontend App\n(React/Next.js)]
    LB --> API_GW[API Gateway\n(FastAPI / Auth)]

    subgraph "SENA Control Plane (Cloud / Central)"
        API_GW --> Queue[Task Queue\n(Redis / RabbitMQ)]
        
        Queue --> Worker1[Orchestrator Worker]
        Queue --> Worker2[Orchestrator Worker]
        
        Worker1 <--> Neural[Model Router]
        Neural <--> SaaS_LLM[Enterprise LLM\n(Azure OpenAI / Bedrock)]
        Neural <--> Local_LLM[Private LLM\n(vLLM Cluster)]
        
        Worker1 <--> VectorDB[(Vector DB\nQdrant / Milvus)]
        Worker1 <--> SQL[(Relational DB\nUsers / Audit Logs)]
    end

    subgraph "Customer A Environment"
        ProxyA[SENA Satellite Proxy] 
        ProxyA -->|Secure Tunnel| API_GW
        ProxyA -->|SSH| RackA[Rack A Servers]
    end

    subgraph "Customer B Environment"
        ProxyB[SENA Satellite Proxy]
        ProxyB -->|Secure Tunnel| API_GW
        ProxyB -->|SSH| RackB[Rack B Servers]
    end

    style FE fill:#e0f7fa,stroke:#006064,stroke-width:2px
    style Worker1 fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style ProxyA fill:#f3e5f5,stroke:#4a148c
    style ProxyB fill:#f3e5f5,stroke:#4a148c
```

**Key Improvements:**

1. **Satellite Proxies:** The "Brain" lives in the cloud, but the "Hands" (Satellite Proxy) live in the customer's secure network. No inbound firewall ports needed.
2. **Message Queue:** Frontend never freezes. Requests are queued and handled by scalable workers.
3. **Model Router:** Swaps between "Fast/Cheap" models (for summaries) and "Smart/Expensive" models (for complex reasoning) dynamically.
4. **API Gateway:** Allows integration with Slack, Jira, and PagerDuty (e.g., "Ask SENA" from Slack).
