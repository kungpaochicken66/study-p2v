# Cost model

Study P2V renders structured visuals locally and accepts uploaded audio. It does not invoke paid TTS, image/video generation, hosted composition, or object-storage providers. The model below is a planning aid; all numerical examples are hypothetical currency units, not live prices, vendor quotes, or measured capacity.

## Separate fixed and variable costs

A monthly budget can be expressed as:

```text
monthly_cost = compute + retained_storage + backups + network_egress + operations
cost_per_accepted_video = monthly_cost / accepted_videos
```

Compute may be a fixed server allocation or metered execution. Include idle time for an always-on service. Retained storage includes uploaded audio, visual caches, composition caches, each job's separate artifact copy, and any retained diagnostic media. Backups add both storage and restoration work. Network cost depends on actual downloads and the deployment's egress arrangement.

There is no automatic storage retention or tenant quota. A cached render saves computation but still publishes another artifact copy. PCM scratch at 48 kHz stereo/16-bit uses about 192,000 bytes per second before accounting for decoded inputs, video scratch, and publication staging. Budget disk headroom from peak concurrent work as well as long-term retention; see [operations](operations.md).

If an upstream system supplies narration or other material, account for its costs separately. Such a system is outside the implemented renderer. A proposed provider integration would need a defined contract, credential handling, spend controls, and its own validation before being included as a product capability.

## Model workload mix

Let `p_cold`, `p_warm`, and `p_partial` be the fractions of jobs in each cache state, summing to one. A useful first estimate is:

```text
mean_compute_per_job =
    p_cold * cold_cost + p_warm * warm_cost + p_partial * partial_cost
```

Determine each term with the same candidate, host, and output verification. Warm jobs still incur digest checks, file reads, publication, and a new durable copy. Partial edits depend on how many segments change. Audio replacement with unchanged visual actions can reuse the visuals but still needs audio assembly and composition. Burned subtitle changes require new video encoding; SRT-only changes can reuse MP4 bytes.

Retry costs depend on what is recomputed. Do not multiply every budget line by the retry count when only a narration asset or one segment changed. Failed or unused upstream candidates can also have real costs, so distinguish generated work from accepted output.

## Hypothetical allocation example

Assume a monthly budget of 120 currency units: 80 for compute, 15 for retained state, 10 for backups, 5 for egress, and 10 for operations.

| Accepted videos in the month | Allocated cost per video |
| --- | ---: |
| 100 | 1.20 units |
| 400 | 0.30 units |
| 1,000 | 0.12 units |

The arithmetic does not demonstrate that the selected server can produce any of these volumes. Storage, download demand, and operational effort may also change with volume. Use measured workload capacity and your actual commercial terms before treating the estimate as a budget.

For a separate hypothetical upstream narration service, a rate of 0.02 units per thousand characters would cost 0.06 units for three thousand characters. It is simply a units calculation; Study P2V has no such provider integration or built-in charge.

## Choose resources from measurements

The renderer uses CPU Manim Cairo. Hardware video encoding, if implemented and evaluated, would affect encoding stages rather than automatically accelerating Cairo layout. No GPU throughput or cost comparison is supplied. Avoid converting a short synthetic benchmark directly into a production-video cost.

Compare configurations using accepted output, service/queue latency, peak resource observations, cache mix, and idle utilization. More workers can increase throughput while increasing contention, scratch space, and per-job latency. The supplied Compose limits and application defaults are configurations to test, not financial or capacity commitments. See [performance](performance.md).
