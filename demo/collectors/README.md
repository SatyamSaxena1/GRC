# Demo collector snapshots

Fake data, on purpose. These files are what a customer's collector would return, with a mix of
passing and failing facts (GitHub change control and AWS have gaps; Microsoft 365 and HRMS pass), so the platform can be shown end to end **without a model**:
"Collect evidence" turns them into controls, verdicts, gaps and tasks through the normal pipeline.

Nothing here describes a real organisation: repositories are `demo-org/...` and URLs use the
reserved `.invalid` domain.

## Wiring one up
Collectors are server-side URLs (`DPDP_<SOURCE>_COLLECTOR_URL`, optional `..._TOKEN`). The repository
is public, so a raw URL works:

```
DPDP_GITHUB_COLLECTOR_URL=https://raw.githubusercontent.com/SatyamSaxena1/GRC/main/demo/collectors/github.json
DPDP_AWS_COLLECTOR_URL=https://raw.githubusercontent.com/SatyamSaxena1/GRC/main/demo/collectors/aws.json
DPDP_M365_COLLECTOR_URL=https://raw.githubusercontent.com/SatyamSaxena1/GRC/main/demo/collectors/m365.json
DPDP_HRMS_COLLECTOR_URL=https://raw.githubusercontent.com/SatyamSaxena1/GRC/main/demo/collectors/hrms.json
```

Never point a collector URL at real customer data on a public URL.
`tests/test_demo_collectors.py` keeps these files producing a useful mix as the rules change.
