"""
Commands to manage deployments.
"""
import logging
from datetime import datetime

import dataclasses
import invoke
import pygit2 as git

from catapult import config, utils
from catapult.release import ActionType, get_release, get_releases, put_release

LOG = logging.getLogger(__name__)


@invoke.task(
    help={
        "name": "identifies the project to deploy.",
        "env": "name of the environment where the app will be deployed",
        "version": "version to deploy",
        "bucket": "name of the bucket used to store the deploys",
        "dry": "prepare a release without committing it",
        "yes": "automatic yes to prompt",
        "rollback": "needed to start a rollback",
    },
    default=True,
)
@utils.require_2fa
def start(
    _, name, env, version=None, bucket=None, dry=False, yes=False, rollback=False
):
    """
    Deploy a release on an environment.
    """
    client = utils.s3_client()
    repo = utils.git_repo()

    if version is None:
        release = next(get_releases(client, name), None)

    else:
        release = get_release(client, name, int(version))

    if release is None:
        utils.fatal("Release not found")

    if bucket is None:
        bucket = utils.get_config()["deploy"][env]["s3_bucket"]

    last_deploy = next(get_releases(client, name, bucket=bucket), None)
    if last_deploy is None:
        # first deploy is always None
        changelog_text = release.changelog
        is_rollback = release.rollback

    else:
        # create a changelog from the latest deploy commit
        changelog = utils.changelog(
            repo, git.Oid(hex=release.commit), git.Oid(hex=last_deploy.commit)
        )

        changelog_text = changelog.text
        is_rollback = changelog.rollback

    action_type = ActionType.automated if config.IS_CONCOURSE else ActionType.manual

    release = dataclasses.replace(
        release,
        changelog=changelog_text,
        timestamp=datetime.now(),
        author=utils.get_author(repo, git.Oid(hex=release.commit)),
        rollback=is_rollback,
        action_type=action_type,
    )

    utils.printfmt(release)

    if dry:
        return

    if release.rollback:
        utils.warning("This is a rollback! :warning:\n")

        if not rollback:
            utils.warning("Missing flag --rollback\n")
            utils.fatal("Aborted!")

    if not yes:

        if release.rollback:
            ok = utils.confirm(
                "Are you sure you want to start a rollback deployment?",
                style=utils.TextStyle.yellow,
            )

            if not ok:
                utils.fatal("Aborted!")

        ok = utils.confirm("Are you sure you want to start this deployment?")
        if not ok:
            utils.fatal("Aborted!")

    put_release(client, bucket, name, release)
    utils.success("Started new deployment :rocket:\n")


@invoke.task(
    help={
        "name": "project's name",
        "env": "name of the environment where the app will be deployed",
        "bucket": "name of the bucket used to store the deploys",
    }
)
@utils.require_2fa
def current(_, name, env, bucket=None):
    """
    Show current running version.
    """
    client = utils.s3_client()

    if bucket is None:
        bucket = utils.get_config()["deploy"][env]["s3_bucket"]

    last_deploy = next(get_releases(client, name, bucket=bucket), None)

    if last_deploy:
        utils.printfmt(last_deploy)

    else:
        utils.fatal("Release does not exist")


deploy = invoke.Collection("deploy", start, current)
