# MikroTik DHCP Troubleshooting Guide (Sample)

> Sample/representative documentation for demo and evaluation purposes.
> Structured to mirror real MikroTik RouterOS DHCP documentation.

## Lease shows "expired" but the client still appears connected

This is one of the most common DHCP support tickets and usually has one of
these causes:

1. **The client failed to renew before expiry.** DHCP clients normally
   attempt renewal at 50% of the lease time (T1) and again at 87.5% (T2).
   If both renewal attempts fail — commonly due to a brief outage at the
   DHCP server, or a firewall rule dropping unicast DHCP renewal
   packets — the lease expires even though the client's interface is
   still up with its old IP.

2. **DHCP server pool exhaustion.** If the address pool is near capacity,
   the server may decline to renew a lease it wants to reclaim for a
   higher-priority client. Check `/ip pool print` for remaining
   addresses in the relevant pool.

3. **Clock skew between client and server** can cause a lease to appear
   expired on the server side well before the client believes it has
   expired, especially on devices with an inaccurate RTC.

### Diagnostic steps

- Check `/ip dhcp-server lease print` for the lease's `status` field and
  `expires-after` value.
- If `status=expired` but the client is actively passing traffic, the
  lease record is stale relative to the client's actual state — this
  resolves cleanly with a lease reset rather than indicating a deeper
  network problem.
- If leases are expiring for many clients simultaneously, suspect DHCP
  server-side issues (pool exhaustion, service restart) rather than a
  per-client problem.

### Remediation

- **Resetting the lease** (`/ip dhcp-server lease remove` followed by
  the client re-requesting, or forcing a renew) clears the stale record
  and is the correct first action for an isolated expired lease with an
  otherwise-healthy client.
- If lease expiry is happening across many clients on the same DHCP
  server, do not reset leases one at a time — investigate the DHCP
  server itself (pool size, uptime, logs) first.

## DHCP client gets no address at all

Distinct from the above — check DHCP discovery, not lease renewal:

- Confirm the DHCP server is enabled on the correct interface/VLAN.
- Confirm no competing DHCP server (rogue or misconfigured) is answering
  first — `/ip dhcp-server` will not show leases it never issued.
- Check pool exhaustion — a full pool causes DHCPDISCOVER requests to go
  unanswered rather than producing an error the client can act on.
