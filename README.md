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
