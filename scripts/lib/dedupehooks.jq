# dedupehooks.jq — shared hook-entry deduplication for Smith's settings.json.
#
# Claude Code runs every command in every entry of an event's array, so the unit
# that must be unique is the individual (matcher, command) pair — NOT the entry.
# Deduplicating whole entries by (matcher + hooks-array) cannot collapse the same
# commands regrouped across fragment versions: {A,B,C}, {A,C,B,D} and {A,B} are
# three distinct keys, so A survives three times and runs three times per Stop.
#
# dedupe_event walks an event's entries in order and keeps a command the FIRST
# time it is seen for a given matcher, dropping later repeats and discarding any
# entry left with no hooks. Entry order — and therefore hook chain order — is
# preserved, so callers that depend on ordering (e.g. manifest-updater.sh running
# last in the PostToolUse chain) are unaffected.
def dedupe_event:
  reduce .[] as $entry (
    {seen: {}, out: []};
    . as $state
    | (($entry.matcher // "*") | tostring) as $matcher
    | (reduce ($entry.hooks // [])[] as $hook (
        {seen: $state.seen, kept: []};
        ($matcher + "|" + ($hook | tostring)) as $key
        | if (.seen | has($key))
          then .
          else .seen += {($key): true} | .kept += [$hook]
          end
      )) as $result
    | {
        seen: $result.seen,
        out: (
          if ($result.kept | length) > 0
          then $state.out + [($entry | .hooks = $result.kept)]
          else $state.out
          end
        )
      }
  )
  | .out;

# dedupe_hooks applies dedupe_event to every event in a `hooks` object.
def dedupe_hooks:
  to_entries
  | map({key: .key, value: (.value | dedupe_event)})
  | from_entries;
