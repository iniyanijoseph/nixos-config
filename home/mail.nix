{ pkgs, ... }:
let
  # Cinny's web client already handles pasted File objects, but the Tauri
  # desktop wrapper does not expose clipboard images to that handler. Patch
  # the frontend to read the image through Tauri's clipboard-manager plugin,
  # then encode the raw RGBA pixels as a PNG File before handing it to Cinny.
  cinnyUnwrappedWithImagePaste = pkgs.cinny-unwrapped.overrideAttrs (old: {
    postPatch = (old.postPatch or "") + ''
      cat > src/app/hooks/useFilePasteHandler.ts <<'EOF'
import { useCallback, ClipboardEventHandler } from 'react';
import { getDataTransferFiles } from '../utils/dom';

type TauriClipboardImage = {
  rgba: () => Promise<Uint8Array>;
  size: () => Promise<{ width: number; height: number }>;
  close: () => Promise<void>;
};

type TauriClipboardManager = {
  readImage: () => Promise<TauriClipboardImage>;
};

type TauriWindow = Window & {
  __TAURI__?: {
    clipboardManager?: TauriClipboardManager;
  };
};

const clipboardImageFile = async (): Promise<File | undefined> => {
  const manager = (window as TauriWindow).__TAURI__?.clipboardManager;
  if (!manager) return undefined;

  let image: TauriClipboardImage | undefined;
  try {
    image = await manager.readImage();
    const [{ width, height }, rgba] = await Promise.all([image.size(), image.rgba()]);

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) return undefined;

    const pixels = new Uint8ClampedArray(rgba);
    context.putImageData(new ImageData(pixels, width, height), 0, 0);

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/png')
    );
    if (!blob) return undefined;

    return new File([blob], 'clipboard.png', { type: 'image/png' });
  } catch {
    // No image in the clipboard (or the backend rejected this clipboard
    // format). Fall through to Cinny's normal browser paste handling.
    return undefined;
  } finally {
    if (image) await image.close().catch(() => undefined);
  }
};

export const useFilePasteHandler = (onPaste: (file: File[]) => void): ClipboardEventHandler =>
  useCallback(
    async (evt) => {
      const tauriImage = await clipboardImageFile();
      if (tauriImage) {
        evt.preventDefault();
        onPaste([tauriImage]);
        return;
      }

      const files = getDataTransferFiles(evt.clipboardData);
      if (files) onPaste(files);
    },
    [onPaste]
  );
EOF
    '';
  });

  cinnyWithImagePaste = pkgs.cinny.override {
    cinny-unwrapped = cinnyUnwrappedWithImagePaste;
  };

  # cinny-desktop already depends on tauri-plugin-clipboard-manager, so this
  # only registers the existing plugin, exposes its global JS API, and grants
  # read-image permission. No Cargo dependencies or fixed-output hashes change.
  cinnyDesktopWithImagePaste =
    (pkgs.cinny-desktop.override { cinny = cinnyWithImagePaste; }).overrideAttrs (old: {
      postPatch = (old.postPatch or "") + ''
        substituteInPlace src/lib.rs \
          --replace-fail \
            '.plugin(tauri_plugin_dialog::init())' \
            '.plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())'

        ${pkgs.jq}/bin/jq \
          '.app.withGlobalTauri = true' \
          tauri.conf.json > tauri.conf.json.tmp
        mv tauri.conf.json.tmp tauri.conf.json

        ${pkgs.jq}/bin/jq \
          '.permissions += ["clipboard-manager:allow-read-image"] | .permissions |= unique' \
          capabilities/migrated.json > capabilities/migrated.json.tmp
        mv capabilities/migrated.json.tmp capabilities/migrated.json
      '';
    });
in
{
  # Manage Thunderbird itself through Home Manager so its add-on policy is
  # reproducible too. Provider for Google Calendar 128.5.12 fixes the repeated
  # Google OAuth prompt seen with Thunderbird 152 / provider 128.5.11.
  programs.thunderbird = {
    enable = true;
    policies.ExtensionSettings."{a62ef8ec-5fdc-40c2-873c-223b8a6925cc}" = {
      installation_mode = "normal_installed";
      install_url = "https://addons.thunderbird.net/thunderbird/downloads/file/1048156/provider_for_google_calendar-128.5.12-tb.xpi";
      updates_disabled = false;
    };
  };

  home.packages = [
    # element-desktop
    cinnyDesktopWithImagePaste
  ];
}
