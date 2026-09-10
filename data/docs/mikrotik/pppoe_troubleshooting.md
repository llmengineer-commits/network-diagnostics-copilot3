# MikroTik PPPoE Troubleshooting Guide (Sample)

> Sample/representative documentation for demo and evaluation purposes.
> Structured to mirror real MikroTik RouterOS PPPoE documentation. Replace
> with your own licensed vendor manuals for production use — see README.

## PPPoE session drops repeatedly

A PPPoE session that connects and then drops after a short period, rather
than failing to connect at all, usually points to one of three causes:

1. **LCP keepalive timeout.** The PPPoE server sends periodic LCP echo
   requests to confirm the client is still alive. If the client does not
   respond within the configured timeout (default: 10 failed retries at
   30-second intervals under `ppp profile`), the server tears down the
   session and logs `LCP timeout (no keepalive response)`. This is the
   single most common cause of intermittent PPPoE drops on last-mile
   connections with marginal signal.

2. **MTU/MRU mismatch.** If the client's MTU does not match the PPPoE
   server's MRU, large packets fragment or get silently dropped,
   eventually triggering a keepalive failure even though the underlying
   link is fine. Check `interface pppoe-client print` for the negotiated
   MRU and compare against the client's configured MTU (should generally
   be 1480 for PPPoE over Ethernet).

3. **Authentication or session limit issues.** If a subscriber has more
   than one device attempting to establish a PPPoE session with the same
   credentials, the PPPoE server may terminate the older session when the
   newer one authenticates. Check `ppp active print` for duplicate
   usernames with different caller-ids.

### Diagnostic steps

- Check `interface pppoe-server monitor <session>` for uptime and the last
  disconnect reason.
- Cross-reference the disconnect reason against the causes above.
- If the reason is an LCP timeout and it recurs for the same subscriber,
  suspect a physical-layer issue (loose cabling, marginal DSL/fiber
  signal) rather than a configuration problem — restarting the session
  will not fix a recurring LCP timeout caused by unstable line quality.

### Remediation

- **Restarting the session** (`/interface pppoe-server remove` on the
  active session, or a request from the client side) clears a stuck
  session but does not fix an underlying line-quality issue. Use this
  when the session has hung with no recent disconnect reason, not as a
  first response to a repeating LCP timeout.
- For recurring LCP timeouts, escalate to a physical-layer check before
  repeatedly restarting the session — restarting a session repeatedly on
  a bad line trains the subscriber to expect the fix, when the real issue
  is a truck roll.

## PPPoE fails to establish at all (no session ever appears)

Different from the above — check PADI/PADO exchange first:

- Confirm the PPPoE server is listening on the correct interface
  (`/interface pppoe-server print`).
- Confirm no VLAN mismatch between the client-facing interface and the
  PPPoE server binding.
- Check for a service-name mismatch between client and server
  configuration — a non-matching service-name causes the server to
  silently ignore PADI discovery packets.
