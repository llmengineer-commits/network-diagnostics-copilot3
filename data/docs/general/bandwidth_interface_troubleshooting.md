# Bandwidth and Interface Troubleshooting Guide (Sample)

> Sample/representative documentation for demo and evaluation purposes.
> Written to cover MikroTik and Huawei interface-statistics conventions.

## Link is saturated / customers reporting slow speeds

Before assuming congestion, distinguish between three distinct causes that
present similarly to an end user:

1. **True saturation.** `rx_bps`/`tx_bps` on the WAN-facing interface is
   at or near `capacity_bps` for sustained periods. This is genuine
   congestion — the fix is capacity planning or traffic shaping, not a
   configuration error.

2. **Packet drops with headroom remaining.** If `rx_drops`/`tx_drops` are
   climbing but throughput is well under capacity, suspect a duplex
   mismatch, a failing SFP/cable, or a queue misconfiguration rather than
   raw congestion — increasing bandwidth will not fix a drop problem
   caused by a bad physical link.

3. **Asymmetric complaint pattern.** If only a subset of subscribers
   report slowness while aggregate interface stats look healthy, the
   bottleneck is more likely per-subscriber queue/shaping configuration,
   not the shared uplink.

### Diagnostic steps

- Pull current interface stats (`rx_bps`, `tx_bps`, `rx_drops`,
  `tx_drops`, `capacity_bps`) rather than relying on a customer's
  subjective "it's slow."
- Compute utilization as `rx_bps / capacity_bps` (and the tx equivalent).
  Sustained utilization above ~85% during peak hours is a reasonable
  threshold for flagging true saturation.
- If drops are present but utilization is low, prioritize a physical-
  layer check (cabling, SFP, duplex settings) over a bandwidth
  conversation with the customer.

### Remediation

- True saturation: escalate for capacity upgrade or apply/adjust traffic
  shaping — this is not something the support desk resolves by itself.
- Drops with headroom: schedule a physical inspection of the affected
  interface; do not treat this as a bandwidth problem.
- Per-subscriber complaints with healthy aggregate stats: review that
  subscriber's queue/shaping rule specifically rather than the shared
  uplink.
