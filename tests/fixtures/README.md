# Development fixtures

`synthetic-polls.json` contains invented example polls, not actual polling results.
Its fields follow VoteHub's documented and observed JSON schema. Use `--all`
when previewing this fixed-date fixture. Tests also build synthetic pagination
metadata to verify that an unverified partial collection fails before sending.
