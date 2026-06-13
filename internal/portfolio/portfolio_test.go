package portfolio

import "testing"

func TestAnalyzeArgs(t *testing.T) {
	args := AnalyzeArgs(true, 5)
	want := []string{"portfolio", "analyze", "--top", "5", "--details"}
	for i := range want {
		if args[i] != want[i] {
			t.Fatalf("args[%d] = %q, want %q", i, args[i], want[i])
		}
	}
}

func TestBuildArgs(t *testing.T) {
	args := BuildArgs()
	if len(args) != 2 || args[0] != "portfolio" || args[1] != "build" {
		t.Fatalf("unexpected build args: %#v", args)
	}
}
