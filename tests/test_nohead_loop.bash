
#!/bin/bash

loop_count=10
gap_time=3

# usage: ./test_nohead_run.bash <command to run UCAgent>

loop_index=0

function is_ucagent_complete(){
    json_file=".ucagent_info.json"
    target_key="all_completed"
    if [[ -f "$json_file" ]]; then
        result=$(jq -r ".${target_key} == true" "$json_file")
        echo "$result"
        return 0
    fi
    echo "false"
    return 1
}

while (( loop_index < loop_count )); do
    cmp=$(is_ucagent_complete)
    echo "Check UCAgent completion status: $cmp"
    if [[ $cmp == "true" ]]; then
        echo "UCAgent has completed all stages."
        exit 0
    else
        echo "Run index: $((loop_index))" > /tmp/ucagent_run_info.txt
        $@
    fi
    ((loop_index++))
    sleep $gap_time
done

echo "UCAgent did not complete all stages within $loop_count attempts." >> /tmp/ucagent_run_info.txt
