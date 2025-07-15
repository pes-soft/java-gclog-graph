#!/usr/bin/env python3
#
# Script to generate graph from Java garbage collector log
#

import argparse
import re
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
import matplotlib.collections as mcollections
import datetime

app_version = "1.1"
app_homepage = "https://github.com/pes-soft/java-gclog-graph"

def parse_args():
    parser = argparse.ArgumentParser(description=f'Script to generate graph from Java garbage collector log')
    parser.add_argument('-f', '--logfile', help='Path to the input GC log file')
    parser.add_argument('-o', '--output', default='./java-gclog-graph.png', help='Path to the output PNG file (default is ./java-gclog-graph.png)')
    parser.add_argument('-d', '--datetime-format', default='%Y-%m-%dT%H:%M:%S.%f%z', help='Format of timestamp in GC log (default is ISO 8601: %%Y-%%m-%%dT%%H:%%M:%%S.%%f%%z)')
    parser.add_argument('-t', '--tail-time', help='Graph only the last seconds before the last data entry (supports suffix m,h,d,w; default is to graph all)')
    parser.add_argument('-m', '--heap-mode', choices=['change','after','before'], default='change', help='Graph heap change either before GC, or after GC, or as a line with heap change (default is line with change)')
    parser.add_argument('-V', '--version', action='store_true', help='Print current version and exit')
    return parser.parse_args()

def resolve_bytes_suffix(bytes_str):
    suffixmap = {'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4}
    if bytes_str[-1:] in suffixmap.keys():
        return int(bytes_str[:-1]) * int(suffixmap[bytes_str[-1:]])
    return int(bytes_str)
         
def resolve_time_suffix(seconds_str):
    suffixmap = {'m': 60, 'h': 60*60, 'd': 60*60*24, 'w': 60*60*24*7}
    if seconds_str[-1:] in suffixmap.keys():
        return int(seconds_str[:-1]) * int(suffixmap[seconds_str[-1:]])
    return int(seconds_str)

def limit_array_values(array, n, limit):
    return [x for i in range(0, len(array) - n + 1, n) if array[i] > limit for x in array[i:i + n]]
         
def parse_gc_log(path, datetime_format):
    print (f"Parsing GC log: '{path}'")
    prt = 0
    memratesize = 1024 ** 2
    gc_heap_used = []
    fullgc_heap_used = []
    heap_free = []
    starts = []
    version = None
    with open(path) as f:
        for line in f:
            # g1gc sample: [2025-07-07T10:49:33.324+0200][825925.772s][info][gc          ] GC(34861) Pause Young (Concurrent Start) (G1 Humongous Allocation) 3784M->2661M(8192M) 48.725ms
            l = re.search(r"^\[([^\]]+)\]\[(\d+\.\d+)s\]\[([^\]]+)\]\[([^\]]+)\] (.*)$", line)
            if l and l.group(1):
                ts = datetime.datetime.strptime(l.group(1), datetime_format)
                rt = float(l.group(2))
                if not prt or rt < prt:
                    starts.append(ts - datetime.timedelta(seconds=rt))
                m = re.search(r"(Pause Young|Full GC)\s+(\([^)]+\)).*\s+(\d+[KMG])->(\d+[KMG])\((\d+[KMG])\)\s+(\d+\.\d+)", l.group(5))
                if m and m.group(1):
                    gctype = m.group(1)
                    gcreason = m.group(2)
                    before = resolve_bytes_suffix(m.group(3)) / memratesize
                    after = resolve_bytes_suffix(m.group(4)) / memratesize
                    maxheap = resolve_bytes_suffix(m.group(5)) / memratesize
                    #pause_sec = float(m.group(6))
                    if gctype == "Full GC":
                        fullgc_heap_used.append(ts)
                        fullgc_heap_used.append([before,after])
                    elif gctype == "Pause Young":
                        gc_heap_used.append(ts)
                        gc_heap_used.append([before,after])
                    heap_free.append(ts)
                    heap_free.append(maxheap)
                if version is None:
                    m = re.search(r"Version:\s+(\S+)", l.group(5))
                    if m and m.group(1):
                        version = m.group(1)
                continue
            # standard gc sample: 2025-06-29T06:36:19.401+0200: 13.146: [Full GC (Metadata GC Threshold) [PSYoungGen: 19983K->0K(1136640K)] [ParOldGen: 176K->19827K(1398272K)] 20159K->19827K(2534912K), [Metaspace: 20747K->20747K(1069056K)], 0.0996065 secs] [Times: user=0.31 sys=0.01, real=0.10 secs]
            l = re.search(r"^(\S+):\s+(\d+\.\d+):\s+\[(GC|Full GC)\s+(\([^)]+\)).*?\s+(\d+[KM])->(\d+[KMG])\((\d+[KMG])\),.*?\s+(\d+\.\d+) secs\]", line)
            if l and l.group(1):
                ts = datetime.datetime.strptime(l.group(1), datetime_format)
                rt = float(l.group(2))
                if not prt or rt < prt:
                    starts.append(ts - datetime.timedelta(seconds=rt))
                prt = rt
                gctype = l.group(3)
                gcreason = l.group(4)
                before = resolve_bytes_suffix(l.group(5)) / memratesize
                after = resolve_bytes_suffix(l.group(6)) / memratesize
                maxheap = resolve_bytes_suffix(l.group(7)) / memratesize
                #pause_sec = float(l.group(8))
                if gctype == "Full GC":
                    fullgc_heap_used.append(ts)
                    fullgc_heap_used.append([before,after])
                elif gctype == "GC":
                    gc_heap_used.append(ts)
                    gc_heap_used.append([before,after])
                heap_free.append(ts)
                heap_free.append(maxheap)
                continue
            if version is None:
                l = re.search(r"\([^\)]*([0-9]\.[0-9]\.[0-9][0-9a-z_-]+)[^\(]*\)", line)
                if l and l.group(1):
                    version = l.group(1)
    return version, fullgc_heap_used, gc_heap_used, heap_free, starts

def plot_data(version, fullgc_heap_used, gc_heap_used, heap_free, starts, output_file, heap_mode=False):
    if heap_mode == "change":
        heap_time_text = 'change by'
    else:
        heap_time_text = heap_mode
    if heap_free:
        tz = heap_free[0].tzname()
    else:
        tz = 'GMT'
    print (f"Plotting graph to '{output_file}' (heap {heap_time_text} GC, timezone {tz})")
    color_heap_free = (0.55, 0.75, 0.25, 0.50)
    color_gc_change = (0.25, 0.25, 1.00, 1.00)
    color_gc_line = (0.35, 0.35, 1.00, 1.00)
    color_fullgc_change = (1.00, 0.25, 0.25, 1.00)
    # Plot
    plt.figure(figsize=(16, 8))
    plt.text(heap_free[0], 0, 'Text Here', fontsize=12,
         bbox=dict(facecolor='lightblue', alpha=0.5, boxstyle='round'), transform=plt.gcf().transFigure)
    ts_min = min(heap_free[0::2])
    ts_max = max(heap_free[0::2])
    plt.text(ts_min, ts_min, 'Start: ' + ts_min.strftime('%Y-%m-%d %H:%M:%S'), fontsize=12, color='red')
    plt.text(ts_max, ts_min, 'End:   ' + ts_max.strftime('%Y-%m-%d %H:%M:%S'), fontsize=12, color='red')
    # Allocated heap
    plt.vlines(heap_free[0::2], ymin=0, ymax=heap_free[1::2], colors=color_heap_free, linewidth=4, label='Allocated Heap')
    # Garbage collection
    if heap_mode == 'change':
        gcs = []
        fgcs = []
        gcs = [[[x, ys[0]], [x, ys[1]]] for x, ys in zip(mdates.date2num(gc_heap_used[0::2]), gc_heap_used[1::2])]
        fgcs = [[[x, ys[0]], [x, ys[1]]] for x, ys in zip(mdates.date2num(fullgc_heap_used[0::2]), fullgc_heap_used[1::2])]
        c = mcollections.LineCollection(gcs, linewidths=1, color=color_gc_change, label=f'Heap change by GC')
        plt.gca().add_collection(c)
        c = mcollections.LineCollection(fgcs, linewidths=1, color=color_fullgc_change, label=f'Heap change by Full GC')
        plt.gca().add_collection(c)
        plt.plot(fullgc_heap_used[0::2], [i[1] for i in fullgc_heap_used[1::2]], 'r^', markersize=10, label=f'Heap after Full GC')
    else:
        if heap_mode == 'before':
            gcs = [i[0] for i in gc_heap_used[1::2]]
            fgcs = [i[0] for i in fullgc_heap_used[1::2]]
        else:
            gcs = [i[1] for i in gc_heap_used[1::2]]
            fgcs = [i[1] for i in fullgc_heap_used[1::2]]
        # GC
        plt.vlines(gc_heap_used[0::2], ymin=0, ymax=gcs, colors=color_gc_line, linewidth=2)
        plt.plot(gc_heap_used[0::2], gcs, marker='o', color=color_gc_change, markersize=1, label=f'Heap {heap_time_text} GC')
        # Full GC
        plt.plot(fullgc_heap_used[0::2], fgcs, 'r^', markersize=10, label=f'Heap {heap_time_text} Full GC')
    # Process start
    for i, x_val in enumerate(starts):
        plt.axvline(x=x_val, color='black', linestyle='-', linewidth=1, label='Start' if i == 0 else None)
    # Disable scientific notation on the y-axis
    plt.gca().yaxis.set_major_formatter(ticker.FormatStrFormatter('%d'))
    # Date format for x-axis
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d\n%H:%M:%S\n%Z', tz=tz))
    plt.gcf().autofmt_xdate()
    # Grid
    plt.grid(True, axis='both', linestyle='--', color='black', linewidth=1)
    # Legend
    plt.legend(loc='lower center')
    # Title and labels
    plt.title(f'GC Log (Java {version})')
    plt.xlabel('Time')
    plt.ylabel('Memory (MB)')
    plt.savefig(output_file)
    plt.close()

def main():
    args = parse_args()
    if args.version:
        print (f"java-gclog-graph.py Version: {app_version} Homepage: {app_homepage}")
        exit(1)
    if not args.logfile:
        print (f"ERROR: The following argument is required: logfile")
        exit(1)
    version, fullgc_heap_used, gc_heap_used, heap_free, starts = parse_gc_log(args.logfile, args.datetime_format)
    if version is None:
        version = 'unknown version'
    if not starts:
        print(f"ERROR: Could not find any valid entry in GC log")
        exit(2)
    if args.tail_time:
        tail_time = resolve_time_suffix(args.tail_time)
        last_ts = max(fullgc_heap_used[0::2] + gc_heap_used[0::2])
        limit_ts = last_ts - datetime.timedelta(seconds=tail_time)
        fullgc_heap_used = limit_array_values(fullgc_heap_used, 2, limit_ts)
        gc_heap_used = limit_array_values(gc_heap_used, 2, limit_ts)
        heap_free = limit_array_values(heap_free, 2, limit_ts)
        starts = limit_array_values(starts, 1, limit_ts)
    plot_data(version, fullgc_heap_used, gc_heap_used, heap_free, starts, args.output, heap_mode=args.heap_mode)

if __name__ == '__main__':
    main()
