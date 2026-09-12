# Pilot transport amendment: retain the timeout and finish undispatched slots

Recorded after the initial transport stopped, before answer-quality inspection or aggregate scoring. The prompt, contexts, expected answers, model, budgets and statistical definitions remain unchanged.

## Observed stop

The original runner, frozen at `9ece9b9`, stopped after a 90.169-second `TimeoutError` in `test-0316`, arm B, repeat 2 (zero-based). Its checkpoint contains 647 attempted slots: 533 stop completions, 113 length failures and one uncertain timeout. It did not produce a final result. The remaining 103 planned slots were never dispatched. No timeout retry occurred.

The original checkpoint is preserved verbatim, SHA-256 `547c173cebac53cc59e4f673b73b0fe3dedd98603e11a2c9557833cc8216c7c8`. The uncertain request ID is `a8879e9f8946a324aab53128227ea1928ac2232425b3e2230e6feed4cc1445cd`. Its outcome and charge are unknown; no missing answer is reconstructed or presumed correct.

## Bounded continuation

A separately attributed continuation may dispatch **only the 103 request identities absent from that exact original checkpoint**, preserving the original order, request bodies and reservations. It must not resend the timeout or any completed/truncated request. The original checkpoint stays unchanged. A new checkpoint uses the guarded terminal-write repair at `e77c0d7`; that repair changes crash recovery, not a request or scoring rule. Any further uncertainty stops this continuation and requires another explicit review; it does not trigger retries or silent fallback.

The fixed model remains `vertex_ai/gemini-3.8-flash` on the same private provider, temperature 0, reasoning effort `low`, completion limit 1,024, input limits 8,192 for A/C/D/E and 16,384 for B. Manifest SHA-256 is `e807eacb8b49a965f1c53257a7903d9006f122b1cc7facc935e5798988e872ce`; prompt SHA-256 is `3bb012d59e1a712665f130637fd1c38c7d406d53d0bba5751039bf530ed7b497`. Request identity and the original prefix are checked before sending anything.

The original whole-plan reservation stays **6,737,967 input and 768,000 output tokens for 750 slots**, including the timeout's reserved 15,241 input and 1,024 output tokens. Continuing absent slots adds no duplicate reservation or request beyond that plan. Private-provider dollar rates remain unknown. The continuation reports its own subset reservation, observed usage and unknown charges separately.

Reconstruction from the frozen inputs fixes the continuation's exact subset ceiling at **922,241 input and 105,472 output tokens**. All 103 slots are in repeat 2, spanning 21 questions: 20 A, 20 B, and 21 each C/D/E. They run from `test-0316`/C through `test-0499`/E. The driver must enforce these subset ceilings in addition to retaining the original whole-plan accounting.

## Publication and interpretation

Publish the original checkpoint, separately generated continuation evidence and an audited union of their disjoint request records. Retain the original records exactly as JSON values, with the original raw-byte hash, both source revisions, context/prompt hashes and separate timing provenance. A union containing the timeout must be labeled **all planned slots accounted for, one outcome uncertain**; it is not a successful 750-response run and must not pass the strict all-terminal pilot verifier.

The frozen analysis still uses all 50 questions and three planned repeats. The uncertain attempt is a failure in the preregistered accuracy/recovery denominators and unknown in completed-only citation/false-abstention audits. Its missing usage remains missing, and its charge is not assumed zero. Truncated attempts likewise remain failures. Report per-arm status counts and the transport interruption; the gap and separate dispatch phase prevent a controlled timing comparison. No prompt, threshold, completion limit, contrast or scoring rule is selected from partial answer outcomes.

Dispatch phase is confounded with question and time; `test-0316` itself spans phases. Even an unchanged returned model alias cannot establish an unchanged provider backend. Do not interpret phase differences causally or claim backend stability from the identity guard alone.
