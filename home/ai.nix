{ pkgs, ... }:
{
  home.packages = with pkgs; [
    codex
  ];

  # Codex uses ChatGPT authentication rather than an API key.
  # Full access is intentional here: no command approvals and no Codex sandbox.
  xdg.configFile."codex/config.toml".text = ''
    forced_login_method = "chatgpt"
    approval_policy = "never"
    sandbox_mode = "danger-full-access"

    # Keep routine coding inexpensive/fast.
    model_reasoning_effort = "low"
    plan_mode_reasoning_effort = "low"

    # Optional: pin Luna later if it is exposed to this ChatGPT/Codex account.
    # model = "gpt-5.6-luna"
  '';
}
