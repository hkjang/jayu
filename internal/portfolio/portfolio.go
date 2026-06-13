package portfolio

import "strconv"

// BuildArgs returns the Python CLI arguments for refreshing the portfolio CSV.
func BuildArgs() []string {
	return []string{"portfolio", "build"}
}

// AnalyzeArgs returns the Python CLI arguments for portfolio exposure analysis.
func AnalyzeArgs(details bool, top int) []string {
	if top <= 0 {
		top = 20
	}
	args := []string{"portfolio", "analyze", "--top", strconv.Itoa(top)}
	if details {
		args = append(args, "--details")
	}
	return args
}
