#!/usr/bin/env bash
set -euo pipefail
fail() { echo "$*" >&2; exit 1; }
probe() { ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=width,height,r_frame_rate,nb_read_frames -of csv=p=0 "$1"; }
duration() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }
match_duration() {
  awk -v a="$(duration "$1")" -v b="$(duration "$2")" 'BEGIN { d=a-b; if(d<0)d=-d; exit(d>0.085) }' || fail "Durations differ: inspect timing before processing."
}
case "${1:-help}" in
  extract)
    [ "$#" -eq 4 ] || fail 'Usage: media.sh extract source.mp4 working.mp4 soundtrack.wav'
    ffmpeg -v error -n -i "$2" -map 0:v:0 -vf 'scale=w=min(960\,iw):h=min(960\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2,fps=24' -an -c:v libx264 -crf 18 -pix_fmt yuv420p "$3"
    ffmpeg -v error -n -i "$2" -map 0:a:0 -vn -c:a pcm_s24le "$4"
    ;;
  pitch)
    [ "$#" -eq 3 ] || fail 'Usage: media.sh pitch isolated-vocals.wav pitched-vocals.wav'
    [ ! -e "$3" ] || fail 'Output already exists.'
    rubberband --pitch 3 "$2" "$3"
    match_duration "$2" "$3"
    ;;
  composite)
    [ "$#" -eq 5 ] || fail 'Usage: media.sh composite working.mp4 depth.mp4 white-subject-mask.mp4 composite.mp4'
    [ "$(probe "$2")" = "$(probe "$3")" ] || fail 'Working and depth dimensions, frame rates or frame counts differ.'
    [ "$(probe "$2")" = "$(probe "$4")" ] || fail 'Working and mask dimensions, frame rates or frame counts differ.'
    ffmpeg -v error -n -i "$2" -i "$3" -i "$4" -filter_complex '[0:v]setpts=PTS-STARTPTS,format=gbrp[b];[1:v]setpts=PTS-STARTPTS,format=gbrp[d];[2:v]setpts=PTS-STARTPTS,format=gray[m];[b][d][m]maskedmerge[v]' -map '[v]' -an -c:v libx264 -crf 18 -pix_fmt yuv420p "$5"
    ;;
  embed)
    [ "$#" -eq 4 ] || fail 'Usage: media.sh embed composite.mp4 pitched-vocals.wav prepared.mp4'
    match_duration "$2" "$3"
    ffmpeg -v error -n -i "$2" -i "$3" -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k "$4"
    ;;
  restore)
    [ "$#" -eq 4 ] || fail 'Usage: media.sh restore generated.mp4 original-source.mp4 final.mp4'
    match_duration "$2" "$3"
    ffmpeg -v error -n -i "$2" -i "$3" -map 0:v:0 -map 1:a:0 -c copy -movflags +faststart "$4"
    original_hash=$(ffmpeg -v error -i "$3" -map 0:a:0 -c copy -f hash -hash sha256 -)
    final_hash=$(ffmpeg -v error -i "$4" -map 0:a:0 -c copy -f hash -hash sha256 -)
    [ "$original_hash" = "$final_hash" ] || fail 'Original audio packet hash differs in export.'
    echo 'Verified: complete first source audio stream copied byte-for-byte.'
    ;;
  *)
    echo 'Commands: extract, pitch, composite, embed, restore. Run a command without arguments for usage.'
    ;;
esac
