package scheduler

import (
	"testing"
	"time"
)

func TestCronExpression(t *testing.T) {
	expr, err := CronExpression(4)
	if err != nil {
		t.Fatal(err)
	}
	if expr != "0 */4 * * *" {
		t.Fatalf("expr = %q", expr)
	}
}

func TestNextRun(t *testing.T) {
	now := time.Date(2026, 6, 13, 9, 30, 0, 0, time.UTC)
	next, err := NextRun(now, 4)
	if err != nil {
		t.Fatal(err)
	}
	if next.Hour() != 12 || next.Minute() != 0 {
		t.Fatalf("next = %s", next)
	}
}
