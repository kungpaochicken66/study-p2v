# Engineering tradeoffs

These principles explain Study P2V's current design and help evaluate changes. They are engineering guidance, not a record of completed deployment or performance acceptance. See [architecture](architecture.md) for the implementation and [validation](validation.md) for evidence requirements.

## Prefer structured content to executable input

A bounded storyboard gives the service predictable limits for text, durations, mathematical trees, and target IDs. It also lets validation happen before expensive media work. Arbitrary scene code would move scheduling, safety, and reproducibility into caller-controlled execution. New visual capabilities should extend the data model and trusted renderer together.

Native media still has a separate trust boundary. Rejecting caller code does not make uploaded audio harmless to a decoder. Installation, process budgets, unprivileged execution, volume permissions, and resource/network policy remain deployment responsibilities.

## Separate visual identity from narration identity

Visual cache keys should describe pixels and actions. Audio digests and subtitle wording belong to composition identity when they do not change those pixels or actions. This makes narration replacement and segment editing useful forms of reuse.

A full-composition hit is also a publication operation: input digests, cached media, and the durable output still need verification. Cache availability must improve efficiency without changing the meaning of success. Per-key locks coordinate identical work, while namespace separation prevents content reuse across authentication boundaries.

## Resolve time once

Frames, audio samples, and subtitle timestamps have different granularities. Resolve effective video frames first, use those durations for global offsets, and quantize absolute audio endpoints. Independent rounding of small clip lengths can disagree at shared boundaries.

Visual and audio alignment need observations of the final media: decoded waveforms and pixels around a cue trigger. A correct cue JSON document or matching container duration cannot establish that the intended object appeared at the intended moment.

## Encode only when content requires it

Conforming silent H.264 segments can be reused and concatenated without another video encode. One continuous PCM track permits one final AAC encode. Sidecar subtitles preserve the video stream; burning captions changes its pixels and therefore requires video encoding.

Stream copying depends on more than codec names and dimensions. Profile, level, time base, and extradata must be compatible. Rejecting mismatches protects output validity even when transcoding everything would appear simpler. Measure render and encode counts alongside timing to ensure an optimization actually removed work.

## Fail unreadable layouts explicitly

Actual font measurements matter more than character counts. Different glyphs and nested mathematics change object dimensions, while resolution changes only the pixel representation of a fixed logical canvas. Minimum readable sizes and safe-area checks make content overflow an actionable error.

For equations and worked examples, an exclusive region keeps the current step readable. Every overlaid step needs an explicit reveal cue. Splitting dense content into steps is often more effective than shrinking it indefinitely.

## Distinguish state from bytes

SQLite records an accepted job and its outcome. Filesystem manifests and independently read artifact bytes verify publication. Neither evidence substitutes for the other. Cancellation must compete with success through the state transaction, and retries should retain the original outcome under a new ID.

A file can outlive a cancelled job or become damaged after successful publication. Preserve the state meaning, refuse invalid downloads, and recover through a consistent backup or new job. Do not repair apparent success by rewriting hashes or terminal states.

## Measure the relevant workload

Cold rendering, full reuse, and partial editing exercise different paths. Throughput and queue latency depend on worker count, namespace concurrency, codec threads, and the input mix. Sampled CPU/RSS estimates have limits and cannot serve as exact billing or memory guarantees.

Short synthetic clips are useful controlled fixtures. They do not establish the capacity of long narrated videos, complex mathematics, or a deployment host. Choose concurrency from measured service and end-to-end latency, verified output, and resource headroom. Use [performance](performance.md) for repeatable measurement and [costs](costs.md) for budget structure.
