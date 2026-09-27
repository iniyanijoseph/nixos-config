{ pkgs, ... }:
{
  home.packages = with pkgs; [
    opencode
  ];

  # OpenCode is terminal-native, so it can run beside Helix in Kitty without
  # adding an Electron editor. Credentials stay out of the Nix store; connect
  # providers interactively with /connect inside OpenCode.
  xdg.configFile."opencode/opencode.jsonc".text = ''
    {
      "$schema": "https://opencode.ai/config.json",

      "agent": {
        "build": {
          "model": "google/gemini-3.8-flash#low"
          // To use ChatGPT later, run /connect -> OpenAI, then swap the line
          // above for:
          // "model": "openai/gpt-5.6-luna#low"
        },
        "plan": {
          "model": "google/gemini-3.8-flash#low"
          // To use ChatGPT later, run /connect -> OpenAI, then swap the line
          // above for:
          // "model": "openai/gpt-5.6-luna#low"
        }
      }
    }
  '';
}
