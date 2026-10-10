# Product constraints

- Preserve the existing black-and-white, magazine-like reading interface, typography,
  composition and mouth presentation. Do not redesign the visual identity as part of
  feature work without an explicit request.
- This is an AI-native librarian. New abilities should primarily be available through
  spoken conversation and the existing Telegram conversation. The librarian performs
  the action and confirms its actual outcome. Do not add a reading-app control panel
  or make the reader manage the librarian's internal state.
- Every reader utterance must be captured as text automatically, including questions,
  comments, childhood memories, tangents and interrupted/unanswered remarks. Saving
  must never depend on an explicit "remember this" request or a successful answer.
  Do not retain original audio recordings. Keep a complete verbatim transcript AND
  separate automatically organized notes/summaries, with links back to original turns.
  Unknown categories remain visible; summarization must not discard content.
- Keep quotation, reader thought and model explanation distinct and source-linked.
  Never claim something was saved before the write succeeds.
- Preserve the user's provider configuration. Tests use temporary library homes and
  local fake services, never the personal library or real Telegram deliveries.
- Raw records and source files are the evidence. Completion is not proof of mastery.
- Device testing and seven days of real use must be reported separately from mocks.
