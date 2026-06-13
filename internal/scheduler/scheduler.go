package scheduler

import (
	"fmt"
	"time"
)

// CronExpression returns a standard five-field cron expression for an hourly cadence.
func CronExpression(everyHours int) (string, error) {
	if everyHours <= 0 || everyHours > 24 {
		return "", fmt.Errorf("everyHours must be between 1 and 24")
	}
	return fmt.Sprintf("0 */%d * * *", everyHours), nil
}

// NextRun returns the next aligned run time for a repeated hourly cadence.
func NextRun(now time.Time, everyHours int) (time.Time, error) {
	if everyHours <= 0 || everyHours > 24 {
		return time.Time{}, fmt.Errorf("everyHours must be between 1 and 24")
	}
	base := now.Truncate(time.Hour)
	for {
		if base.After(now) && base.Hour()%everyHours == 0 {
			return base, nil
		}
		base = base.Add(time.Hour)
	}
}
