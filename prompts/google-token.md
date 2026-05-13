Stage Google credentials for CLIs on this machine. Bouncer's
`get_google_token` MCP tool returns a bouncer-issued bearer that
gcloud, gws, and curl will use transparently. The proxy unwraps it
to your real Google credential on every upstream call.

# 1. Fetch the bouncer-issued token
Call the MCP tool `get_google_token`. The response has:

    {
      "service": "google",
      "access_token": "<encrypted-bearer>",
      "refresh_token": "<encrypted-bearer>",
      "credential_path": "~/.config/bouncer/google-creds.json",
      "credential_mode": "0600",
      "file_template": "<the JSON shape gcloud honors>",
      "env": { "GOOGLE_APPLICATION_CREDENTIALS": "{{ .Path }}" }
    }

# 2. Write the credentials file
Render `file_template` with the response's `access_token`. The
template is a Go text/template with `{{ .AccessToken }}` as the only
substitution. Write the result to `credential_path`, replacing the
leading `~` with `$HOME`. Mode is `credential_mode` (octal, so a
shell `chmod 0600` works).

For Google the rendered shape is gcloud's "authorized_user" form:

    {
      "type": "authorized_user",
      "access_token": "<bouncer-issued bearer>"
    }

# 3. Append the per-service subsection
Append the following block to the bouncer fragment in the project's
instruction file (CLAUDE.md / .cursorrules / AGENTS.md / etc.). If a
`### google` heading already exists below `## bouncer`, skip.

    ### google
    Set GOOGLE_APPLICATION_CREDENTIALS to
    [[ .CredentialPath ]] when invoking gws, gcloud, or any tool
    honoring that variable. Example:

        GOOGLE_APPLICATION_CREDENTIALS=[[ .CredentialPath ]] \
          bouncer-wrap gws drive list

    For curl:

        bouncer-wrap curl -H "Authorization: Bearer \
          $(jq -r .access_token [[ .CredentialPath ]])" <url>

# Done
Tell the user:
    "Google credentials staged. Try: bouncer-wrap gws drive list"
