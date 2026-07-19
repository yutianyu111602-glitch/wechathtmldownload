# soundSubmissionGateway

Mini-program-only Cloud Function that initializes the current CloudBase v3 SDK with the invocation context, derives `openId` and `appId` from the runtime identity, signs a fixed sound-submission body, and calls the fixed `weekly-api` CloudRun route. Request fields never supply identity.

Required environment variables:

- `SOUND_GATEWAY_WECHAT_APP_ID`
- `SOUND_GATEWAY_CLOUDRUN_SERVICE`
- `SOUND_SUBMISSIONS_INGRESS_HMAC_SECRET` (at least 32 bytes; must match CloudRun)
- `TCB_ENV` is provided by CloudBase and binds storage and ingress to the deployed environment.

Deploy this function for mini-program invocation only. The `probe` action is signed and non-writing; the release gate must prove it succeeds while a direct public POST with forged `X-WX-*` headers is rejected.
