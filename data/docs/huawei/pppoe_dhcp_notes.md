# Huawei Enterprise Router PPPoE & DHCP Notes (Sample)

> Sample/representative documentation for demo and evaluation purposes.
> Written to mirror Huawei VRP (Versatile Routing Platform) CLI and
> terminology conventions, which differ from MikroTik RouterOS in naming
> but cover the same underlying protocols.

## PPPoE session instability on Huawei AR-series routers

Huawei's PPPoE implementation surfaces the same underlying causes as
other vendors (LCP keepalive failure, MTU mismatch, duplicate sessions)
but through different diagnostic commands:

- `display pppoe-server session all` shows active sessions with their
  `Session-State` and, for recently torn-down sessions, the termination
  cause under the session's `Disconnect-Reason` field.
- A `Disconnect-Reason` of `Idle-Timeout` or `Keepalive-Failure` maps to
  the same LCP-timeout root cause covered for MikroTik: check physical
  line quality before repeatedly restarting the session.
- MTU/MRU issues on VRP show up as fragmented PADI/PADS negotiation in
  `debugging pppoe-server event` output — configured MTU is set under
  the virtual-template interface, not the physical interface.

### Remediation

- `reset pppoe-server session user-name <username>` restarts a specific
  session — functionally equivalent to a MikroTik session restart, and
  subject to the same guidance: appropriate for a stuck session, not a
  substitute for fixing a recurring physical-layer problem.

## DHCP lease anomalies on Huawei VRP

- `display dhcp server ip-in-use` lists current leases with their state.
  A lease showing `Expired` while the client is still active on the LAN
  is the same "stale lease record" scenario as MikroTik, and is resolved
  the same way: reset the individual lease rather than restarting the
  whole DHCP service.
- `reset dhcp server ip-in-use pool <pool-name> <ip-address>` clears a
  single lease.
- Pool exhaustion is visible via `display dhcp server pool-name
  <pool-name>` — check `Idle IP num` before assuming a per-client fault.

## When documentation alone isn't enough

Huawei firmware releases fix specific PPPoE/DHCP bugs fairly frequently;
if a symptom doesn't match any known cause above, check for a firmware
advisory rather than assuming a configuration error — this project's
threat-intelligence tool (`check_security_advisories`) and general web
search fallback (`web_search_troubleshooting`) exist for exactly this
gap between "documented behavior" and "current, fast-moving vendor
advisories."
