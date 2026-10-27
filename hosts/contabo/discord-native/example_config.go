package main

// Keep the legacy bridge's template export compatible with the modern bridge
// CLIs. The normal config/registration parser and upgrade path remain upstream.
import (
	"fmt"
	"os"

	flag "maunium.net/go/mauflag"
)

var contaboGenerateExample = flag.MakeFull("e", "generate-example-config",
	"Write the embedded example configuration and quit.", "false").Bool()

func (br *DiscordBridge) HandleFlags() bool {
	if !*contaboGenerateExample {
		return false
	}
	// A template export must never replace an existing private configuration.
	file, err := os.OpenFile(br.ConfigPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err == nil {
		_, err = file.WriteString(br.GetExampleConfig())
		if err == nil {
			err = file.Sync()
		}
		closeErr := file.Close()
		if err == nil {
			err = closeErr
		}
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "Failed to export example configuration:", err)
		os.Exit(1)
	}
	return true
}
