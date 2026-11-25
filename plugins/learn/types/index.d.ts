declare module 'claude-code' {
  interface PluginState {
    learn: {
      // The report date the pane shows; empty means the newest.
      selected: Shaped<string>
      // The reject reason being typed, per recommendation ID. A key being
      // present means that recommendation's reject box is open.
      drafts: Shaped<Record<string, string>>
    }
  }
}
