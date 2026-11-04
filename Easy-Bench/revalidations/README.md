# Maintainer revalidation receipts

These receipts bind an unchanged community study to its SHA-256, reviewed PR head,
trusted validator commit, coverage check and full current regrading result.
To verify a receipt, check the study file hash and run the validator from the
named commit against the named PR. `study validate --file PATH` repeats grading;
`campaign status --file PATH` checks campaign coverage separately.

The recorded grader belongs to the original report; `regraded_with_sha256`
identifies the maintainer regrader. A receipt does not attest model identity or
prove inference provenance. It is not a new model run or another statistical study.
