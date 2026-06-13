package notify

import "testing"

func TestArgsDefaultChannel(t *testing.T) {
	args := Args("")
	want := []string{"notify", "--channel", "kakao"}
	for i := range want {
		if args[i] != want[i] {
			t.Fatalf("args[%d] = %q, want %q", i, args[i], want[i])
		}
	}
}
