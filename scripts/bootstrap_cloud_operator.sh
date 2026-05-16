#!/bin/zsh
set -euo pipefail

MODE="${1:-status}"
INSTALL_ROOT="${INSTALL_ROOT:-$HOME/.local/google-cloud-sdk}"
BIN_LINK_DIR="${BIN_LINK_DIR:-$HOME/.local/bin}"

say_status() {
  printf "%s\n" "$1"
}

gcloud_present() {
  command -v gcloud >/dev/null 2>&1
}

determine_archive_url() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  if [[ "$os" != "Darwin" ]]; then
    echo "Unsupported OS: $os" >&2
    return 1
  fi

  if [[ "$arch" == "arm64" ]]; then
    echo "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-darwin-arm.tar.gz"
    return 0
  fi
  if [[ "$arch" == "x86_64" ]]; then
    echo "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-darwin-x86_64.tar.gz"
    return 0
  fi

  echo "Unsupported architecture: $arch" >&2
  return 1
}

print_next_steps() {
  say_status ""
  say_status "Next steps:"
  say_status "  1. export PATH=\"$BIN_LINK_DIR:\$PATH\""
  say_status "  2. gcloud auth login"
  say_status "  3. gcloud auth application-default login"
  say_status "  4. gcloud config set project <project-id>"
  say_status "  5. ./run_inferno_cloud_control_plane.sh"
  say_status "  6. ./scripts/deploy_cloud_run_job.sh"
}

status_report() {
  if gcloud_present; then
    say_status "gcloud present: $(command -v gcloud)"
    gcloud --version | head -n 1
  else
    say_status "gcloud present: no"
    say_status "Install with:"
    say_status "  ./scripts/bootstrap_cloud_operator.sh install"
  fi
  say_status "Expected install root: $INSTALL_ROOT"
  say_status "Expected bin link dir: $BIN_LINK_DIR"
}

install_gcloud() {
  local url tmpdir archive parent_dir extracted_dir
  url="$(determine_archive_url)"
  tmpdir="$(mktemp -d)"
  archive="$tmpdir/google-cloud-cli.tar.gz"
  parent_dir="$(dirname "$INSTALL_ROOT")"
  extracted_dir="$parent_dir/google-cloud-sdk"

  say_status "Downloading Google Cloud CLI..."
  curl -fsSL "$url" -o "$archive"

  mkdir -p "$parent_dir"
  rm -rf "$extracted_dir"
  tar -xzf "$archive" -C "$parent_dir"

  if [[ "$extracted_dir" != "$INSTALL_ROOT" ]]; then
    rm -rf "$INSTALL_ROOT"
    mv "$extracted_dir" "$INSTALL_ROOT"
  fi

  say_status "Running Cloud SDK installer..."
  "$INSTALL_ROOT/install.sh" --quiet --path-update=false --command-completion=false --usage-reporting=false

  mkdir -p "$BIN_LINK_DIR"
  ln -sf "$INSTALL_ROOT/bin/gcloud" "$BIN_LINK_DIR/gcloud"
  ln -sf "$INSTALL_ROOT/bin/gsutil" "$BIN_LINK_DIR/gsutil"
  ln -sf "$INSTALL_ROOT/bin/bq" "$BIN_LINK_DIR/bq"

  say_status "Google Cloud CLI installed locally."
  status_report
  print_next_steps
}

case "$MODE" in
  status)
    status_report
    ;;
  install)
    install_gcloud
    ;;
  *)
    echo "Usage: $0 [status|install]" >&2
    exit 1
    ;;
esac
