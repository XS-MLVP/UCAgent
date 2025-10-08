
#!/bin/bash

loop_count=100
gap_time=10

# Usage: test_nohead_run.bash <command to run Code Agents>
#  eg: test_nohead_run.bash npx @qwen-code/qwen-code@latest -y -p '<your_prompts>'

info_file="/tmp/ucagent_run_info.txt"

time_start=$(date +%s)
loop_index=0
echo "Start time: $(date)" > "$info_file"

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
        echo "UCAgent has completed all stages at $(date)." >> "$info_file"
        time_end=$(date +%s)
        elapsed_time=$((time_end - time_start))
        echo "Total elapsed time: $((elapsed_time / 3600)) hours $((elapsed_time / 60 % 60)) minutes $((elapsed_time % 60)) seconds" >> "$info_file"
        exit 0
    else
        echo "Run index: $((loop_index)) at $(date)" >> "$info_file"
        $@
    fi
    ((loop_index++))
    sleep $gap_time
done

time_end=$(date +%s)
elapsed_time=$((time_end - time_start))
echo "End time: $(date)" >> "$info_file"
echo "Total elapsed time: $((elapsed_time / 3600)) hours $((elapsed_time / 60 % 60)) minutes $((elapsed_time % 60)) seconds" >> "$info_file"
echo "Reached maximum loop count ($loop_count) without completing all stages." >> "$info_file"
exit 1
