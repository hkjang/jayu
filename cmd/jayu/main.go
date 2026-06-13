package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
)

func findProjectRoot(start string) (string, error) {
	current, err := filepath.Abs(start)
	if err != nil {
		return "", err
	}
	for {
		if _, err := os.Stat(filepath.Join(current, "pyproject.toml")); err == nil {
			return current, nil
		}
		parent := filepath.Dir(current)
		if parent == current {
			return "", errors.New("pyproject.toml not found")
		}
		current = parent
	}
}

func commandFor(root string, args []string) (*exec.Cmd, error) {
	executable := filepath.Join(root, ".venv", "bin", "jayu")
	if runtime.GOOS == "windows" {
		executable = filepath.Join(root, ".venv", "Scripts", "jayu.exe")
	}
	if _, err := os.Stat(executable); err == nil {
		return exec.Command(executable, args...), nil
	}
	if _, err := exec.LookPath("uv"); err != nil {
		return nil, errors.New("neither the project virtualenv nor uv is available")
	}
	uvArgs := append([]string{"run", "jayu"}, args...)
	return exec.Command("uv", uvArgs...), nil
}

func run(args []string) error {
	root, err := findProjectRoot(".")
	if err != nil {
		return err
	}
	command, err := commandFor(root, args)
	if err != nil {
		return err
	}
	command.Dir = root
	command.Stdin = os.Stdin
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	return command.Run()
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		var exitError *exec.ExitError
		if errors.As(err, &exitError) {
			os.Exit(exitError.ExitCode())
		}
		fmt.Fprintln(os.Stderr, "jayu-go:", err)
		os.Exit(1)
	}
}
