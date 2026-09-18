# One simple browser test

This is the easiest way to check that PlanReview works. You are not applying anything to AWS.

## Before opening the browser

In PowerShell, from the `PlanReview` folder, start the server:

```powershell
.\.venv\Scripts\python.exe -m uvicorn engine.api:app --host 127.0.0.1 --port 8000
```

Wait for `Uvicorn running on http://127.0.0.1:8000`.

## In the browser

Open `http://127.0.0.1:8000`.

1. On **Create task**, leave **Replay** selected. Click **Create task**.
   - Expected: you see **Confirm contract**.

2. Click **Use three-color demo scope**.
   - Expected: the contract says the maximum changed resources is `3`.
   - Expected: `networking` is absent from the denied categories. This makes networking a REVIEW item for this demonstration.

3. Click **Confirm contract**, then **Continue to plan review**.
   - Expected: the contract status looks sealed or confirmed.

4. Click **Run & evaluate plan**.
   - Expected: wait a few seconds for Terraform.
   - Expected: you see exactly these three result types:

| Resource | Meaning | Expected label |
|---|---|---|
| `aws_lambda_function.dev_api` | Memory changes from 512 to 1024, which matches the contract. | **ALLOW** |
| `aws_security_group.api` | A networking change exists but is not pre-approved. | **REVIEW** |
| `aws_s3_bucket_public_access_block.assets` | Four public-access safeguards change from true to false. | **DENY** |

5. Click **Try apply** or **Verify block via API**.
   - Expected: **BLOCKED**.
   - Expected text includes `DENY` and `spawned: false`.
   - Meaning: PlanReview did not start Terraform apply because the S3 change is unsafe.

This is a successful test. Seeing **DENY** and **BLOCKED** is correct; it proves the safety check works.

## If you only want the simplest test

Use **Replay** and do steps 1–5 above. Do not select **Live Strands / Ollama** until the replay test works.
