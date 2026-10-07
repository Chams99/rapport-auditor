# Private GitHub repository and manual VPS updates

Rapport Auditor is in the private repository `Chams99/rapport-auditor`. If the VPS already has GitHub access for this repository through its account SSH identity or HTTPS credential helper, use it; no new key setup is needed. A deploy key attached only to the portfolio repository cannot read this one. The optional repository-scoped read-only key below is only for a VPS without another authorized GitHub identity. There is no GitHub Actions workflow or automatic deployment: publishing a change and updating the VPS are separate, manual steps.

This candidate has no `LICENSE`/`COPYING` file or license metadata. Keep it private and do not infer public redistribution rights from the GitHub repository.

## Quick path after one-time co-hosting setup

Before starting the app, the operator must configure the persistent internal Traefik network and fixed peer address, set the exact `RAPPORT_AUDITOR_TRUSTED_PROXY`, choose `RAPPORT_AUDITOR_APP_MEMORY_LIMIT` and `RAPPORT_AUDITOR_APP_CPU_LIMIT` from measured VPS capacity, and create the private secret at the path in `deployment/.env.traefik`. Complete the DNS, forwarding-header, timeout, access-log, and capacity checks in [the co-hosting runbook](COHOSTING.md). These are one-time host setup steps; they cannot be filled with guessed values.

Use an already authorized GitHub SSH identity or HTTPS credential helper for this private repository. From Windows PowerShell, connect first:

```powershell
ssh my-vps
```

At the VPS shell, clone the private repository on first setup using its existing authorized authentication method. Set `REVIEWED_SHA` to the immutable commit SHA approved for the initial release, then verify the pin before applying the separate Rapport Compose project. For later updates, use the existing clone and the update steps below.

```sh
mkdir -p "$HOME/services"
git clone https://github.com/Chams99/rapport-auditor.git "$HOME/services/rapport-auditor"
cd "$HOME/services/rapport-auditor"
git fetch origin main --prune
REVIEWED_SHA=replace-with-reviewed-release-commit-sha
git cat-file -e "$REVIEWED_SHA^{commit}"
git switch --detach "$REVIEWED_SHA"
test "$(git rev-parse HEAD)" = "$REVIEWED_SHA"
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml config --quiet
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml build app
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml up -d
```

If the clone says permission denied, stop and use an existing authorized account identity or the optional read-only deploy-key setup below. Do not make the repository public to bypass authentication. If using that optional key, replace the clone URL's host with `github-rapport-auditor` after configuring the SSH alias. The profile does not create the Traefik network or secret, and these commands do not deploy the portfolio.

## Create the private repository once

Run this from the reviewed clean checkout on Windows after its initial commit is approved. The authenticated GitHub account should be `Chams99`; the login command prints only the account name. Stop if the working tree is dirty, the account differs, or any remote already exists.

```powershell
Set-Location 'D:\1_DEV\1_A1_UNIVERSITY\0_PFE\rapport-auditor'
git status --short
git remote
gh api user --jq .login

# Run once, after reviewing the source and commit.
gh repo create Chams99/rapport-auditor --private --source . --remote origin --push
gh repo view Chams99/rapport-auditor --json name,isPrivate,url
git rev-parse HEAD
git ls-remote --symref origin HEAD
```

Confirm the final metadata reports `isPrivate: true`, and that `ls-remote` reports the approved candidate SHA on the default branch. Do not publish this project to the portfolio repository or to the existing `python-Latex` repository. `gh repo create` creates the private remote and pushes the reviewed local branch; it does not configure deployment.

## Optional: add a repository-scoped read-only key

Use this only if the VPS has no existing GitHub account SSH identity with access to this repository. From the operator's normal terminal, connect to the VPS and generate a dedicated key there. Generate it once, under the same Linux account that will own the checkout. The private key stays on the VPS and should never be copied into chat, source control, or GitHub.

From Windows PowerShell, connect to the VPS:

```powershell
ssh my-vps
```

Then run this block at the VPS shell:

```sh
umask 077
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
if [ -e "$HOME/.ssh/rapport-auditor-readonly" ] || [ -e "$HOME/.ssh/rapport-auditor-readonly.pub" ]; then
  echo "Key path already exists; stop and inspect it before continuing."
else
  ssh-keygen -t ed25519 -f "$HOME/.ssh/rapport-auditor-readonly" -C "rapport-auditor VPS read-only" -N "" &&
  chmod 600 "$HOME/.ssh/rapport-auditor-readonly" &&
  cat "$HOME/.ssh/rapport-auditor-readonly.pub"
fi
```

In GitHub, open **Chams99/rapport-auditor → Settings → Deploy keys → Add deploy key**. Paste only the `.pub` value, use a recognizable title such as `Rapport VPS read-only`, and leave **Allow write access** unchecked. A deploy key is attached to one repository, and its private half stays on the server. This passphrase-free key is a persistent read-only credential; limit VPS account access and remove the key from GitHub if the VPS is retired or compromised. See [GitHub's deploy-key instructions](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).

Add this host alias once to `~/.ssh/config` on the VPS so Git uses only this repository's key:

```sshconfig
Host github-rapport-auditor
  HostName github.com
  User git
  IdentityFile ~/.ssh/rapport-auditor-readonly
  IdentitiesOnly yes
```

Restrict the config file and test the connection:

```sh
chmod 600 "$HOME/.ssh/config"
ssh -T git@github-rapport-auditor
```

On the first connection, compare the displayed GitHub SSH host-key fingerprint with [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints) before accepting it. A successful `ssh -T` greeting says GitHub authenticated the key; GitHub does not provide shell access, so the command can exit with status 1.

## Clone and update the checkout

Keep the Rapport checkout separate from the portfolio checkout. Clone it under the operator account's home directory:

```sh
mkdir -p "$HOME/services"
git clone git@github.com:Chams99/rapport-auditor.git "$HOME/services/rapport-auditor"
cd "$HOME/services/rapport-auditor"
git status --short

# Replace this value with the reviewed initial commit SHA supplied by the maintainer.
RAPPORT_RELEASE_SHA='replace-with-reviewed-commit-sha'
git fetch origin main --prune
git show --no-patch --oneline "$RAPPORT_RELEASE_SHA"
git switch --detach "$RAPPORT_RELEASE_SHA"
test "$(git rev-parse HEAD)" = "$RAPPORT_RELEASE_SHA"
git status --short
```

The clone command above uses an existing GitHub account SSH identity. If you configured the optional deploy-key alias, use `git@github-rapport-auditor:Chams99/rapport-auditor.git` as the clone URL instead.

For a later source update, stop if `git status --short` reports local changes. Save the current known-good commit SHA, fetch `main`, and switch to the reviewed immutable commit SHA supplied by the maintainer:

```sh
cd "$HOME/services/rapport-auditor"
git status --short
PREVIOUS_SHA=$(git rev-parse HEAD)
printf 'Previous deployment SHA: %s\n' "$PREVIOUS_SHA"
git fetch origin --prune
# Replace this value with the reviewed commit SHA for the update.
RAPPORT_RELEASE_SHA='replace-with-reviewed-commit-sha'
git show --no-patch --oneline "$RAPPORT_RELEASE_SHA"
git switch --detach "$RAPPORT_RELEASE_SHA"
test "$(git rev-parse HEAD)" = "$RAPPORT_RELEASE_SHA"
```

Compare the selected commit with the approved SHA before building. Record `PREVIOUS_SHA` for rollback. The deploy key is read-only, so it cannot push changes from the VPS. To publish a later change, review and push it from the trusted development checkout. A push alone does not change the running service.

## Apply an update manually

First complete the live network, exact Traefik peer-IP, DNS/TLS, forwarding-header, access-log, timeout, and host-capacity checks in [the co-hosting runbook](COHOSTING.md). Fill in the ignored `deployment/.env.traefik` using the live values and keep the secret on the VPS. Do not copy secret values into shell history, chat, or Git.

After fetching the reviewed commit, use the documented Rapport-only Compose profile from the Rapport checkout. These commands verify required settings, build the app image, and apply the update; they do not deploy the portfolio:

```sh
cd "$HOME/services/rapport-auditor"
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml config --quiet
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml build app
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml up -d
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml ps
```

Only run `build` and `up` after the runbook's preflight passes and `config --quiet` succeeds. Then perform the external HTTPS, synthetic POST, forwarded-IP/quota, readiness, and resource checks there. Do not announce the service from a successful build or `ps` output alone. For rollback, use the Rapport-only command in the runbook; never run the portfolio deployment script for this app.

If the candidate fails after the update, replace the value below with the saved previous SHA and repeat the same quiet config, app build, and Compose `up` commands:

```sh
PREVIOUS_SHA='replace-with-saved-previous-commit-sha'
git switch --detach "$PREVIOUS_SHA"
test "$(git rev-parse HEAD)" = "$PREVIOUS_SHA"
```

Do not use `git reset --hard`, force-push, or remove the Redis volume during rollback.
