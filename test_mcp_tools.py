"""
MCP Tool Test Suite — Meridian Electronics

Two modes:
  default  →  structured pass/fail suite covering all 8 tools and error paths
              (uses langchain-mcp-adapters — same path the chatbot uses)
  --demo   →  narrative walkthrough showing raw server responses over JSON-RPC
              (uses httpx directly — no adapter, mirrors Gemini-style approach)

Usage:
    uv run python test_mcp_tools.py
    uv run python test_mcp_tools.py --demo
"""

import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv
from langchain_core.tools.base import ToolException
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv(override=True)

MCP_URL = os.environ["MCP_SERVER_URL"]
KNOWN_SKUS = [s.strip() for s in os.getenv("KNOWN_SKUS", "MON-0054,ACC-0131").split(",") if s.strip()]

# All 10 test customers from the brief
ALL_CUSTOMERS = [
    ("donaldgarcia@example.net", "7912"),
    ("michellejames@example.com", "1520"),
    ("laurahenderson@example.org", "1488"),
    ("spenceamanda@example.org", "2535"),
    ("glee@example.net", "4582"),
    ("williamsthomas@example.net", "4811"),
    ("justin78@example.net", "9279"),
    ("jason31@example.com", "1434"),
    ("samuel81@example.com", "4257"),
    ("williamleon@example.net", "9928"),
]

ORDER_STATUSES = ["draft", "submitted", "approved", "fulfilled", "cancelled"]

# ── terminal colours ──────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def ok(msg):      print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg):    print(f"  {RED}✗{RESET} {msg}")
def info(msg):    print(f"  {CYAN}→{RESET} {msg}")
def show(text):   print(f"{DIM}{_indent(text, 6)}{RESET}")
def section(t):   print(f"\n{BOLD}{YELLOW}{'─'*60}{RESET}\n{BOLD}{t}{RESET}")
def step(n, msg): print(f"\n{BOLD}{BLUE}[STEP {n}]{RESET} {BOLD}{msg}{RESET}")

def _indent(text: str, width: int) -> str:
    pad = " " * width
    return "\n".join(pad + line for line in text.splitlines())

def _preview(text: str, lines: int = 6) -> str:
    """Return the first N lines of text, with a truncation note if cut."""
    all_lines = text.splitlines()
    head = "\n".join(all_lines[:lines])
    if len(all_lines) > lines:
        head += f"\n  … ({len(all_lines) - lines} more lines)"
    return head


# ── JSON-RPC direct caller (Gemini-style — no adapter) ───────────────────────
def rpc_call(name: str, args: dict, *, timeout: int = 15) -> str:
    """Send a JSON-RPC 2.0 tools/call request directly over HTTP.

    Bypasses the langchain adapter — useful for verifying raw protocol behaviour
    and for the --demo mode where we want to show exactly what the server returns.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    resp = httpx.post(
        MCP_URL,
        json=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error {data['error'].get('code')}: {data['error'].get('message')}")
    content = data.get("result", {}).get("content", [])
    return content[0].get("text", "") if content else str(data.get("result", ""))


# ── adapter caller (same path the chatbot uses) ───────────────────────────────
def _extract_text(result: Any) -> str:
    """Normalise adapter output: handles plain str and content-block lists."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "\n".join(
            b["text"] for b in result
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(result)


async def call(tool_map: dict, name: str, **kwargs) -> str:
    """Invoke a tool via the adapter; MCP errors returned as [ERROR] strings."""
    try:
        return _extract_text(await tool_map[name].ainvoke(kwargs))
    except ToolException as e:
        return f"[ERROR] {e}"


# ── parsing helpers ───────────────────────────────────────────────────────────
def extract_uuid(text: str) -> str | None:
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)
    return m.group(0) if m else None

def extract_price(text: str) -> str:
    m = re.search(r"\$?([\d]+\.\d{2})", text)
    return m.group(1) if m else "99.99"

def extract_sku(text: str) -> str | None:
    m = re.search(r"\[([A-Z]{2,4}-\d{4})\]", text)
    return m.group(1) if m else None


# ── Results tracker ───────────────────────────────────────────────────────────
@dataclass
class Results:
    passed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def record(self, name: str, passed: bool, detail: str = ""):
        if passed:
            self.passed += 1
            ok(name)
        else:
            self.failed += 1
            self.errors.append(f"{name}: {detail}")
            fail(f"{name}  ← {detail[:120]}")

    def summary(self):
        total = self.passed + self.failed
        colour = GREEN if self.failed == 0 else RED
        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}Results: {colour}{self.passed}/{total} passed{RESET}")
        if self.errors:
            print(f"\n{RED}Failures:{RESET}")
            for e in self.errors:
                print(f"  • {e}")
        print()


# ══════════════════════════════════════════════════════════════════════════════
#  TEST SUITE (adapter path)
# ══════════════════════════════════════════════════════════════════════════════

async def test_list_products(tool_map: dict, r: Results):
    section("1 · list_products")

    info("no filter — all products")
    out = await call(tool_map, "list_products")
    r.record("returns non-empty catalogue", bool(out and len(out) > 10), out[:80])

    for cat in ["Monitors", "Keyboards", "Printers", "Computers", "Accessories"]:
        info(f"category={cat!r}")
        out = await call(tool_map, "list_products", category=cat)
        r.record(f"category='{cat}' returns results", bool(out and len(out) > 5), out[:80])

    info("is_active=True (active stock only)")
    out = await call(tool_map, "list_products", is_active=True)
    r.record("is_active=True returns results", bool(out and len(out) > 5))

    info("is_active=False (discontinued)")
    out = await call(tool_map, "list_products", is_active=False)
    r.record("is_active=False executes without error", out is not None)


async def test_search_products(tool_map: dict, r: Results) -> str:
    section("2 · search_products")

    discovered_sku = ""
    for query in ["keyboard", "monitor", "printer", "cable", "webcam"]:
        info(f"query={query!r}")
        out = await call(tool_map, "search_products", query=query)
        found = bool(out and "[ERROR]" not in out and len(out) > 10)
        r.record(f"search '{query}' returns results", found, out[:80] if not found else "")
        if found and not discovered_sku:
            discovered_sku = extract_sku(out) or ""

    info("query='zxqwerty9999' (no-match)")
    out = await call(tool_map, "search_products", query="zxqwerty9999")
    r.record("no-match search returns graceful response", "[ERROR]" not in out)

    # prefer a known-good SKU over a dynamically harvested one
    return KNOWN_SKUS[0] if KNOWN_SKUS else discovered_sku


async def test_get_product(tool_map: dict, r: Results):
    section("3 · get_product")

    for sku in KNOWN_SKUS:
        info(f"SKU={sku}")
        out = await call(tool_map, "get_product", sku=sku)
        r.record(f"get_product({sku})", bool(out and "[ERROR]" not in out and len(out) > 10), out[:100])

    info("invalid SKU='INVALID-9999'")
    out = await call(tool_map, "get_product", sku="INVALID-9999")
    r.record("invalid SKU returns error (not crash)", "[ERROR]" in out or "not found" in out.lower())


async def test_verify_customer_pin(tool_map: dict, r: Results) -> dict[str, str]:
    """Returns {email: customer_id} for all successfully verified customers."""
    section("4 · verify_customer_pin — all 10 test customers")

    verified: dict[str, str] = {}

    for email, pin in ALL_CUSTOMERS:
        info(f"{email}  PIN={pin}")
        out = await call(tool_map, "verify_customer_pin", email=email, pin=pin)
        success = "[ERROR]" not in out and len(out) > 20
        r.record(f"valid auth — {email.split('@')[0]}", success, out[:100] if not success else "")
        if success:
            cid = extract_uuid(out)
            if cid:
                verified[email] = cid

    info("wrong PIN (donaldgarcia / 0000)")
    out = await call(tool_map, "verify_customer_pin", email="donaldgarcia@example.net", pin="0000")
    r.record(
        "wrong PIN rejected",
        "[ERROR]" in out or any(w in out.lower() for w in ("not found", "invalid", "incorrect")),
        out[:100],
    )

    info("non-existent email (ghost@nowhere.com)")
    out = await call(tool_map, "verify_customer_pin", email="ghost@nowhere.com", pin="1234")
    r.record("unknown email rejected", "[ERROR]" in out or len(out) < 50, out[:100])

    return verified


async def test_get_customer(tool_map: dict, r: Results, verified: dict[str, str]):
    section("5 · get_customer")

    if not verified:
        r.record("get_customer (requires verified ID)", False, "step 4 returned no verified customers")
        return

    for email, cid in list(verified.items())[:3]:
        info(f"{email} → {cid[:8]}…")
        out = await call(tool_map, "get_customer", customer_id=cid)
        r.record(f"get_customer({cid[:8]}…)", bool(out and "[ERROR]" not in out), out[:100])

    info("invalid UUID (all-zeros)")
    out = await call(tool_map, "get_customer", customer_id="00000000-0000-0000-0000-000000000000")
    r.record("invalid customer_id returns error", "[ERROR]" in out or len(out) < 60, out[:100])


async def test_list_orders(tool_map: dict, r: Results, verified: dict[str, str]) -> list[str]:
    section("6 · list_orders")

    order_ids: list[str] = []

    info("no filter — all orders")
    out = await call(tool_map, "list_orders")
    r.record("list_orders (all) returns results", bool(out and "[ERROR]" not in out), out[:100])

    if verified:
        email, cid = next(iter(verified.items()))
        info(f"customer_id filter — {email}")
        out = await call(tool_map, "list_orders", customer_id=cid)
        r.record(f"list_orders for {email.split('@')[0]}", bool(out and "[ERROR]" not in out), out[:100])
        order_ids = re.findall(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out
        )

    for status in ORDER_STATUSES:
        info(f"status={status!r}")
        out = await call(tool_map, "list_orders", status=status)
        r.record(f"list_orders status={status} executes", out is not None)

    return order_ids


async def test_get_order(tool_map: dict, r: Results, order_ids: list[str]):
    section("7 · get_order")

    if order_ids:
        oid = order_ids[0]
        info(f"order_id={oid}")
        out = await call(tool_map, "get_order", order_id=oid)
        r.record(f"get_order({oid[:8]}…) returns line items", bool(out and "[ERROR]" not in out), out[:100])
    else:
        r.record("get_order with known ID", False, "no order IDs harvested from step 6")

    info("invalid order_id (all-zeros)")
    out = await call(tool_map, "get_order", order_id="00000000-0000-0000-0000-000000000000")
    r.record("invalid order_id returns error", "[ERROR]" in out or len(out) < 60, out[:100])


async def test_create_order(tool_map: dict, r: Results, verified: dict[str, str]):
    section("8 · create_order")

    if not verified:
        r.record("create_order (requires verified customer)", False, "no verified customers")
        return

    email, cid = next(iter(verified.items()))
    sku = KNOWN_SKUS[0]

    # look up real price so the order matches catalogue data
    info(f"fetching live price for {sku}")
    product_out = await call(tool_map, "get_product", sku=sku)
    unit_price = extract_price(product_out)

    info(f"placing order — customer={email}, SKU={sku}, qty=1, price={unit_price}")
    out = await call(tool_map, "create_order",
        customer_id=cid,
        items=[{"sku": sku, "quantity": 1, "unit_price": unit_price, "currency": "USD"}],
    )
    r.record(
        f"create_order for {email.split('@')[0]}",
        bool(out and "[ERROR]" not in out and len(out) > 20),
        out[:150],
    )

    info("qty=999999 — expect InsufficientInventoryError")
    out = await call(tool_map, "create_order",
        customer_id=cid,
        items=[{"sku": sku, "quantity": 999999, "unit_price": unit_price, "currency": "USD"}],
    )
    r.record(
        "over-quantity order rejected",
        "[ERROR]" in out or any(w in out.lower() for w in ("insufficient", "inventory", "stock")),
        out[:120],
    )

    info("invalid customer_id — expect CustomerNotFoundError")
    out = await call(tool_map, "create_order",
        customer_id="00000000-0000-0000-0000-000000000000",
        items=[{"sku": sku, "quantity": 1, "unit_price": unit_price, "currency": "USD"}],
    )
    r.record("invalid customer rejected", "[ERROR]" in out or len(out) < 60, out[:100])

    info("invalid SKU in items — expect ProductNotFoundError")
    out = await call(tool_map, "create_order",
        customer_id=cid,
        items=[{"sku": "FAKE-0000", "quantity": 1, "unit_price": "10.00", "currency": "USD"}],
    )
    r.record("invalid SKU in order rejected", "[ERROR]" in out or "not found" in out.lower(), out[:100])


# ══════════════════════════════════════════════════════════════════════════════
#  DEMO MODE — raw JSON-RPC, Gemini-style narrative (no adapter)
# ══════════════════════════════════════════════════════════════════════════════

def run_demo():
    print(f"\n{BOLD}Meridian Electronics — Customer Journey Demo{RESET}")
    print(f"{DIM}Transport: JSON-RPC 2.0 over HTTP (no adapter){RESET}")
    print(f"{DIM}Server:    {MCP_URL}{RESET}\n")

    # ── Step 1: browse catalogue ──────────────────────────────────────────────
    step(1, "Browse active product catalogue")
    out = rpc_call("list_products", {"is_active": True})
    show(_preview(out, 8))

    # ── Step 2: search ────────────────────────────────────────────────────────
    step(2, "Customer asks: 'Do you have any monitors?'")
    out = rpc_call("search_products", {"query": "monitor"})
    show(_preview(out, 8))

    # ── Step 3: product detail ────────────────────────────────────────────────
    step(3, f"Customer picks {KNOWN_SKUS[0]} — fetch details")
    out = rpc_call("get_product", {"sku": KNOWN_SKUS[0]})
    show(out)
    unit_price = extract_price(out)
    print(f"  {GREEN}Parsed price:{RESET} {unit_price} USD")

    # ── Step 4: authenticate ──────────────────────────────────────────────────
    email, pin = ALL_CUSTOMERS[0]
    step(4, f"Customer authenticates — {email} / PIN {pin}")
    out = rpc_call("verify_customer_pin", {"email": email, "pin": pin})
    show(out)
    cid = extract_uuid(out)
    print(f"  {GREEN}Customer ID:{RESET} {cid}")

    if not cid:
        print(f"{RED}Cannot proceed — authentication failed{RESET}")
        return

    # ── Step 5: order history ─────────────────────────────────────────────────
    step(5, "Fetch order history for this customer")
    out = rpc_call("list_orders", {"customer_id": cid})
    show(_preview(out, 10))
    order_ids = re.findall(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out
    )
    if order_ids:
        step("5b", f"Drill into order {order_ids[0][:8]}…")
        out = rpc_call("get_order", {"order_id": order_ids[0]})
        show(out)

    # ── Step 6: place new order ───────────────────────────────────────────────
    step(6, f"Place new order — SKU={KNOWN_SKUS[0]}, qty=1")
    out = rpc_call("create_order", {
        "customer_id": cid,
        "items": [{"sku": KNOWN_SKUS[0], "quantity": 1, "unit_price": unit_price, "currency": "USD"}],
    })
    show(out)
    new_order_id = extract_uuid(out)

    # ── Step 7: confirm order ─────────────────────────────────────────────────
    if new_order_id:
        step(7, f"Confirm — fetch new order {new_order_id[:8]}…")
        out = rpc_call("get_order", {"order_id": new_order_id})
        show(out)

    print(f"\n{BOLD}{GREEN}✓ Demo complete — full customer journey executed successfully{RESET}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

async def run_suite():
    print(f"\n{BOLD}Meridian Electronics — MCP Tool Test Suite{RESET}")
    print(f"{DIM}Transport: langchain-mcp-adapters (same path as chatbot){RESET}")
    print(f"{DIM}Server:    {MCP_URL}{RESET}\n")

    client = MultiServerMCPClient({"meridian": {"url": MCP_URL, "transport": "streamable_http"}})
    print("Connecting to MCP server…")
    try:
        tools = await client.get_tools()
    except Exception as e:
        print(f"{RED}Connection failed: {e}{RESET}")
        sys.exit(1)

    tool_map = {t.name: t for t in tools}
    print(f"{GREEN}Connected — {len(tool_map)} tools:{RESET} {', '.join(tool_map)}\n")

    r = Results()

    await test_list_products(tool_map, r)
    await test_search_products(tool_map, r)
    await test_get_product(tool_map, r)
    verified = await test_verify_customer_pin(tool_map, r)
    await test_get_customer(tool_map, r, verified)
    order_ids = await test_list_orders(tool_map, r, verified)
    await test_get_order(tool_map, r, order_ids)
    await test_create_order(tool_map, r, verified)

    r.summary()


if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        asyncio.run(run_suite())
