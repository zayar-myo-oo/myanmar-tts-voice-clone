# Local changes to the Nara Mini v1 frontend

Upstream: https://huggingface.co/YeeNyunn/nara-mini-v1 (Apache-2.0; see LICENSE and NOTICE).
The `frontend/` folder is copied from upstream and modified here. ONNX weights stay
outside Git in `models/nara-mini-v1/onnx/`.

## Changes

- 2026-11-17 `frontend/lexicon_exceptions.tsv`: added `ကမ္ဘာ` → `g-ə b-a-˧` and
  `ကမ္ဘာကြီး` → `g-ə b-a-˧ dʑ-i-˥`. Upstream G2P produced `kaɴ ba`, which a native
  listener heard as English "Canva". The listener confirmed the fix.
