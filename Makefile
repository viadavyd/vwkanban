.PHONY: perf deploy-check

# Every plan §7 target, enforced, on a throwaway stack built from HEAD (asks for sudo
# once: the latency check adds 20 ms netem on its port). See scripts/perf.sh.
perf:
	scripts/perf.sh

# The README's cold deploy (pulled images) in a fresh clone of HEAD, so it also runs from
# a checkout that has its own .env. In a clean checkout: scripts/deploy-check.sh.
deploy-check:
	@tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	git clone -q . "$$tmp/vwk" && "$$tmp/vwk/scripts/deploy-check.sh"
