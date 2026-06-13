package notify

// Args returns the Python CLI arguments for sending a notification.
func Args(channel string) []string {
	if channel == "" {
		channel = "kakao"
	}
	return []string{"notify", "--channel", channel}
}
