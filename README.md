# 🧾 Prosper Assistant

> AI-powered business agent for Nigerian small business owners — built for the **Google Cloud Rapid Agent Hackathon**

Prosper Assistant moves beyond chat. It plans, executes multi-step missions, and takes real actions — sending invoices, tracking debts, recording sales, and giving live business intelligence — all through simple conversation in plain English or Nigerian English.

---

## 🎯 The Problem

There are over **39 million SMEs** in Nigeria. Most have no accountant, no business advisor, and no AI tool built for their reality. They:
- Lose money to unpaid invoices and broken follow-up
- Don't know if their business is profitable until it's too late
- Can't afford modern bookkeeping software
- Speak English or Nigerian English but get foreign-context tools

Prosper Assistant changes that.

---

## ⚡ What It Does

| Capability | Example User Query | Real Action Taken |
|---|---|---|
| Track unpaid invoices | "Who owes me money?" | Queries MongoDB → returns live list |
| Create & send invoices | "Send invoice to Emeka for ₦60,000" | Saves to DB + emails customer instantly |
| Record cash sales | "I sold 20 bags of rice for ₦45,000" | Logs sale + calculates profit |
| Mark invoices paid | "Mark INV-001 as paid" | Updates DB + adjusts customer balance |
| Lifetime business report | "Give me my full business report" | Aggregates sales + invoices + customers |
| Daily summary | "How's my business today?" | Real-time daily revenue and outstanding |
| Specific date queries | "How were sales on 2026-05-10?" | Filters by date and returns analysis |
| All-time summary | "Show me all my sales ever" | Full historical analysis |

---

## 🏗️ Architecture
User Message
        (English or Nigerian English)
                     │
                     ▼
    ┌────────────────────────────────────┐
    │   Google Agent Builder + Gemini    │
    │   Reasons and decides which tool   │
    └────────────────────────────────────┘
                     │
                     ▼
    ┌────────────────────────────────────┐
    │   Prosper Assistant MCP Server     │
    │   FastMCP on Google Cloud Run      │
    └────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐
  │ MongoDB  │ │  Gmail   │ │  Arize   │
  │  Atlas   │ │   API    │ │ Phoenix  │
  │ (Data)   │ │ (Email)  │ │ (Traces) │
  └──────────┘ └──────────┘ └──────────┘

## 🧰 Tech Stack

- **Brain:** Gemini 2.5 Pro (via Google Agent Builder)
- **Orchestration:** Google Cloud Agent Builder
- **MCP Server:** FastMCP with streamable-http transport
- **Deployment:** Google Cloud Run
- **Database:** MongoDB Atlas (Partner MCP integration)
- **Observability:** Arize Phoenix (Partner MCP integration)
- **Email:** Gmail API
- **External Data:** Live USD/NGN exchange rates

---

## 🤝 Partner Integrations (MCP)

### 1. MongoDB Atlas
Powers the entire data layer of Prosper Assistant:
- Stores invoices, sales records, customer data
- Real-time queries when agent calls tools
- Persistent business memory across sessions

### 2. Arize Phoenix
Full observability for every agent decision:
- Traces every MCP tool call
- Monitors latency and token usage
- Shows agent reasoning steps in a live dashboard
- Enables continuous improvement of agent behavior

---

## 🛠️ MCP Tools Available

```python
@mcp.tool() check_unpaid_invoices       # Who owes money
@mcp.tool() record_sale                 # Log a cash sale
@mcp.tool() create_invoice              # Create and email invoice
@mcp.tool() get_business_report         # Today's report
@mcp.tool() get_all_sales_summary       # All-time sales total
@mcp.tool() get_sales_by_date           # Historical date query
@mcp.tool() get_lifetime_business_report # Full business overview
@mcp.tool() mark_invoice_as_paid        # Mark invoice paid
```

---

## 🚀 How to Run Locally

```bash
git clone https://github.com/Eddward82/prosper-assistant
cd prosper-assistant
pip install -r requirements.txt
```

Create a `.env` file:
MONGODB_URI=your_mongodb_connection_string
DB_NAME=prosper-db
GMAIL_USER=your_gmail@gmail.com
GMAIL_APP_PASSWORD=your_gmail_app_password
PHOENIX_API_KEY=your_phoenix_api_key

Run the MCP server:
```bash
python mcp_server.py
```

---

## 🌐 Live Demo

- **Live MCP Server:** `https://prosper-assistant-666245775274.us-central1.run.app/mcp`
- **Agent:** Deployed on Google Cloud Agent Builder

---

## 🏆 Hackathon Submission

**Track:** Google Cloud Rapid Agent Hackathon — Building Agents for Real-World Challenges  
**Partner MCP Integration:** MongoDB Atlas + Arize Phoenix  
**Built by:** Edward Ogunlusi — Lagos, Nigeria

---

## 📈 Future Roadmap

- **WhatsApp integration** — meet Nigerian SMEs where they already are
- **Mobile app (Flutter)** — native Android experience
- **Multi-tenant support** — each business gets isolated data
- **Pidgin English support** — even more accessible language
- **Voice-first agent** — for users with limited literacy
- **Tax filing automation** — CAC, FIRS, LIRS integrations

---

## 📜 License

MIT License — see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgements

- **Google Cloud** for the Agent Builder platform and Gemini API
- **MongoDB** for the partner MCP integration
- **Arize AI** for observability tools
- **Devpost** for hosting this hackathon
- **The Nigerian SME community** — this is built for you


