# Lessons

- Match start/stop hotkey behavior before chasing deeper interception fixes when the user reports an asymmetry.
  - **Why:** The user observed a practical mismatch: start did "space + backspace" while stop only inserted a space. The immediate desired behavior was consistency on stop, not more speculative hotkey interception work.
  - **How to apply:** When debugging hotkey/input issues, first normalize behavior across start/stop paths in `toggle_recording()` if the user is asking for a concrete behavior change, then revisit lower-level interception only if the consistent fallback is still unacceptable.

- Never do long-running work directly inside a Quartz event tap callback.
  - **Why:** After moving the hotkey listener to Quartz, calling `toggle_recording()` synchronously from the tap callback caused paste/focus failures and made the second hotkey stop responding, because recording stop, ASR inference, and sleeps blocked the tap thread.
  - **How to apply:** If a hotkey/event listener is backed by a Quartz event tap, return from the callback immediately and dispatch real work to a separate worker thread.
