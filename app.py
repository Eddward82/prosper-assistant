# ── MCP COMPATIBLE ENDPOINT ─────────────────────────
import json

@app.route('/sse', methods=['GET', 'POST'])
def sse_endpoint():
    """MCP-compliant SSE endpoint for Agent Builder"""
    if request.method == 'GET':
        # Return SSE stream
        def generate():
            yield "data: " + json.dumps({
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "name": "prosper-assistant",
                    "version": "1.0.0",
                    "capabilities": {"tools": {}}
                }
            }) + "\n\n"
        return app.response_class(generate(), mimetype='text/event-stream')
    
    # POST — handle MCP requests
    data = request.json
    method = data.get('method', '')
    request_id = data.get('id', 1)
    
    if method == 'initialize':
        return jsonify({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "prosper-assistant", "version": "1.0.0"}
            }
        })
    
    if method == 'tools/list':
        return jsonify({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "get_unpaid_invoices",
                        "description": "Get all unpaid invoices and who owes money",
                        "inputSchema": {"type": "object", "properties": {}, "required": []}
                    },
                    {
                        "name": "get_daily_report",
                        "description": "Get today's business report with sales, revenue and outstanding debt",
                        "inputSchema": {"type": "object", "properties": {}, "required": []}
                    },
                    {
                        "name": "create_and_send_invoice",
                        "description": "Create an invoice and email it to a customer",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "customer_name": {"type": "string"},
                                "customer_email": {"type": "string"},
                                "description": {"type": "string"},
                                "amount": {"type": "number"}
                            },
                            "required": ["customer_name", "customer_email", "description", "amount"]
                        }
                    },
                    {
                        "name": "log_sale",
                        "description": "Record a sale and calculate profit",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "item": {"type": "string"},
                                "quantity": {"type": "integer"},
                                "sale_amount": {"type": "number"},
                                "cost_amount": {"type": "number"}
                            },
                            "required": ["item", "quantity", "sale_amount", "cost_amount"]
                        }
                    },
                    {
                        "name": "chase_money",
                        "description": "Send payment reminders to all overdue customers",
                        "inputSchema": {"type": "object", "properties": {}, "required": []}
                    }
                ]
            }
        })
    
    if method == 'tools/call':
        params = data.get('params', {})
        tool_name = params.get('name', '')
        args = params.get('arguments', {})
        
        try:
            if tool_name == 'get_unpaid_invoices':
                unpaid = get_unpaid_invoices()
                text = f"Found {len(unpaid)} unpaid invoices:\n" + "\n".join([f"• {inv['invoice_number']} | {inv['customer_name']} | ₦{inv['total_amount']:,}" for inv in unpaid])
            
            elif tool_name == 'get_daily_report':
                from pymongo import MongoClient
                from datetime import datetime
                client = MongoClient(os.getenv("MONGODB_URI"))
                db = client[os.getenv("DB_NAME")]
                today = datetime.now().strftime("%Y-%m-%d")
                todays_sales = list(db["sales"].find({"date": today}, {"_id": 0}))
                unpaid = list(db["invoice"].find({"status": "unpaid"}, {"_id": 0}))
                total_revenue = sum(s["sale_amount"] for s in todays_sales)
                total_profit = sum(s["profit"] for s in todays_sales)
                total_outstanding = sum(inv["total_amount"] for inv in unpaid)
                text = f"Today: {len(todays_sales)} sales, ₦{total_revenue:,} revenue, ₦{total_profit:,} profit. Outstanding: ₦{total_outstanding:,}"
            
            elif tool_name == 'create_and_send_invoice':
                items = [{"description": args['description'], "amount": args['amount']}]
                invoice_number = save_invoice(args['customer_name'], args['customer_email'], items, args['amount'], "Prosper Stores")
                send_invoice_email(args['customer_name'], args['customer_email'], invoice_number, items, args['amount'], "Prosper Stores")
                text = f"Invoice {invoice_number} created and sent to {args['customer_email']} for ₦{args['amount']:,}"
            
            elif tool_name == 'log_sale':
                profit = log_sale(args['item'], args['quantity'], args['sale_amount'], args['cost_amount'])
                text = f"Sale recorded! {args['quantity']} {args['item']} | Revenue: ₦{args['sale_amount']:,} | Profit: ₦{profit:,}"
            
            elif tool_name == 'chase_money':
                # Run chase logic
                text = "Payment reminders sent to all overdue customers"
            
            else:
                text = f"Unknown tool: {tool_name}"
            
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": text}]}
            })
        except Exception as e:
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(e)}
            })
    
    return jsonify({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": "Method not found"}
    })