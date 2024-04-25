import argparse
import socket
import logging
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from time import sleep, time
from struct import unpack_from
from threading import Thread
from . import GracefulExiter, DuplicateFilter, VERSION

VOLT_MAX = pow(2,15)
VOLT_MIN = -pow(2,15)
NUM_ADC = 5
NUM_CH_PER_ADC = 4

logger = logging.getLogger(__name__)
flag = GracefulExiter()

graph_data = []
for n in range(NUM_ADC):
    graph_data.append({"ts": [], "0": [], "1": [], "2": [], "3": []})


def main():
    prog = "nuprism-ctl"
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    parser.add_argument("ip", help="IP address of NuPRISM module")
    parser.add_argument("-a", "--adc", default="all", help="ADC to use")
    parser.add_argument("-p", "--port", type=int, default=1500, help="Port to listen on for UDP packets")
    parser.add_argument("-l", "--log", metavar="file", help="Log to output file")
    parser.add_argument("-s", "--samples", default='1024', help="Maximum samples displayed")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase logging verbosity, can be repeated")

    args = parser.parse_args()

    # Setup logging
    logger.setLevel(logging.DEBUG)
    logger.addFilter(DuplicateFilter())  # add the filter to it

    # Default logging is WARNING, -v gives INFO, -vv gives DEBUG
    levels = [logging.WARNING, logging.INFO, logging.DEBUG]

    # capped to number of levels
    level = levels[min(len(levels) - 1, args.verbose)]    

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    if args.log:
        handler = logging.FileHandler(args.log, mode="w")
    else:
        handler = logging.StreamHandler()

    handler.setLevel(level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    lines = []
    max_samples = int(args.samples)


    def get_data(max_samples):
        global graph_data

        rx_samples_per_adc = [0] * 5
        last_time = time()
        rx_bytes = 0

        # Bind to all interfaces
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setblocking(False)
        udp_socket.bind(('0.0.0.0', args.port))


        while(not flag.exit()):

            current_time = time()
            if current_time > last_time + 2.0:
                print(f"\r                                                                                                                               \r", end='')
                print(f"Bytes per second: {(rx_bytes / (current_time - last_time)) / 1000000:.02f}MB/s  Samples received per adc: {rx_samples_per_adc}",end='\r')
                last_time = current_time
                rx_bytes = 0

            try:
                message, address = udp_socket.recvfrom(1500)

                if len(message) > 0:
                    # Header is 42 bytes
                    num_words, packet_id, frame_id, timestamp, trigger_count, user_word0, user_word1, user_word2, user_word3 = unpack_from(">HIIQIxxxxIIII", message, 0)

                    # ADC Data packet is 1024 bytes vs Tail is 16 additional bytes
                    # print(f"numwords: {num_words} pid: {packet_id}  fid: {frame_id} ts: {timestamp} tc: {trigger_count} u0: 0x{user_word0:08x} u1: 0x{user_word1:08x} u2: 0x{user_word2:08x} u3: 0x{user_word3:08x} len: {len(message)}")

                    rx_bytes += len(message)

                    if len(message) == 1066:                        
                        adc_id = user_word3 >> 24

                        rx_samples_per_adc[adc_id] += 1024

                        for n in range(0, 1024, 64):
                            adc0, adc1, adc2, adc3 = unpack_from("<hhhh", message, 42 + n)                        

                            graph_data[adc_id]["0"].append(adc0)
                            graph_data[adc_id]["1"].append(adc1)
                            graph_data[adc_id]["2"].append(adc2)
                            graph_data[adc_id]["3"].append(adc3)

                            # graph_data[(adc_id*4)+0].append(adc0)
                            # graph_data[(adc_id*4)+1].append(adc1)
                            # graph_data[(adc_id*4)+2].append(adc2)
                            # graph_data[(adc_id*4)+3].append(adc3)

                        # Shorten arrays to maximum allowed length
                        graph_data[adc_id]["0"] = graph_data[adc_id]["0"][-max_samples:]
                        graph_data[adc_id]["1"] = graph_data[adc_id]["1"][-max_samples:]
                        graph_data[adc_id]["2"] = graph_data[adc_id]["2"][-max_samples:]
                        graph_data[adc_id]["3"] = graph_data[adc_id]["3"][-max_samples:]                            

                        # graph_data[(adc_id*4)+0] = graph_data[(adc_id*4)+0][-max_samples:]
                        # graph_data[(adc_id*4)+1] = graph_data[(adc_id*4)+1][-max_samples:]
                        # graph_data[(adc_id*4)+2] = graph_data[(adc_id*4)+2][-max_samples:]
                        # graph_data[(adc_id*4)+3] = graph_data[(adc_id*4)+3][-max_samples:]                            

                    if len(message) == 58:
                        trigger_count0, trigger_count1, global_ts0, global_ts1, global_ts2, global_ts3, trigger_info0, trigger_info1 = unpack_from(">HHHHHHHH", message, 42)

                        trigger_count = trigger_count1 << 16 | trigger_count0
                        global_ts = (global_ts3 << 48) | (global_ts2 << 32) | (global_ts1 << 16) | global_ts0
                        trigger_info = trigger_info1 << 16 | trigger_info0

                        trigger_type = trigger_info & 0xF
                        triggered_adc = (trigger_info >> 4) & 0xF
                        trigger_ch_mask = (trigger_info >> 9) & 0xFFFFF

                        # print(f"trig_type: {trigger_type:d} trig_adc: {triggered_adc:d} mask: 0x{trigger_ch_mask:06X}")


            except (socket.timeout, BlockingIOError) as e:
                # Give the thread a rest so to avoid soft-lock
                sleep(0.001)
     
    # This function is called periodically from FuncAnimation
    def animate(i, graph_data):
        # Draw x and y lists
        if args.adc == "all":
            for i in range(NUM_ADC):
                lines[(i * NUM_CH_PER_ADC) + 0].set_ydata(graph_data[i]["0"])
                lines[(i * NUM_CH_PER_ADC) + 1].set_ydata(graph_data[i]["1"])
                lines[(i * NUM_CH_PER_ADC) + 2].set_ydata(graph_data[i]["2"])
                lines[(i * NUM_CH_PER_ADC) + 3].set_ydata(graph_data[i]["3"])
        else:
            adc_id = int(args.adc) - 1
            lines[0].set_ydata(graph_data[adc_id]["0"])
            lines[1].set_ydata(graph_data[adc_id]["1"])
            lines[2].set_ydata(graph_data[adc_id]["2"])
            lines[3].set_ydata(graph_data[adc_id]["3"])

        return lines

    def init_plot():        
        for idx, a in enumerate(ax):
            if args.adc == "all":
                a.set_title(str(idx + 1), x=0.1, y=0.9)
                a.set_xticks([0, max_samples / 2])
                a.tick_params(labelrotation=315)
            else:
                a.set_title(str(idx + 1))
            a.set_xlim([0, max_samples])
            a.set_ylim(VOLT_MAX, VOLT_MIN)
            a.grid(True)

        return lines

    fig = plt.figure(figsize=(160, 90))

    if args.adc == "all":
        gs = fig.add_gridspec(1, 5, wspace=0.0, hspace=0.0)
        px = gs.subplots(sharex=True)
        ax = [
            px[0],
            px[1],
            px[2],
            px[3],
            px[4],
        ]
        fig.canvas.manager.set_window_title("All ADCs - Voltage over Time")
        fig.text(0.5, 0.04, "Sample #", ha="center", va="center")
        fig.text(
            0.06, 0.5, "Voltage (V)", ha="center", va="center", rotation="vertical"
        )
    else:
        if int(args.adc) < 1:
            args.adc = 1

        elif int(args.adc) > 5:
            args.adc = 5

        gs = fig.add_gridspec(1, hspace=0)
        ax = [gs.subplots(sharex=True)]
        fig.canvas.manager.set_window_title(
            "ADC #" + str(int(args.adc)) + " Voltage over Time"
        )

        plt.ylabel("Voltage (V)")
        plt.xlabel("Sample #")

    plt.ioff()

    for i in range(NUM_ADC):
        for n in range(max_samples):
            graph_data[i]["ts"].append(n)
            graph_data[i]["0"].append(None)
            graph_data[i]["1"].append(None)
            graph_data[i]["2"].append(None)
            graph_data[i]["3"].append(None)

    # Draw x and y lists
    if args.adc == "all":
        for i in range(NUM_ADC):
            (line0,) = ax[i].plot(graph_data[i]["ts"], graph_data[i]["0"], label="0")
            (line1,) = ax[i].plot(graph_data[i]["ts"], graph_data[i]["1"], label="1")
            (line2,) = ax[i].plot(graph_data[i]["ts"], graph_data[i]["2"], label="2")
            (line3,) = ax[i].plot(graph_data[i]["ts"], graph_data[i]["3"], label="3")

            lines.append(line0)
            lines.append(line1)
            lines.append(line2)
            lines.append(line3)

            # Format plot
            for axs in ax:
                axs.label_outer()

        fig.legend(fig.axes[0].lines, ["0", "1", "2", "3"], loc="upper center", ncol=4)

    else:
        adc_id = int(args.adc) - 1

        (line0,) = ax[0].plot(
            graph_data[adc_id]["ts"], graph_data[adc_id]["0"], label="0"
        )
        (line1,) = ax[0].plot(
            graph_data[adc_id]["ts"], graph_data[adc_id]["1"], label="1"
        )
        (line2,) = ax[0].plot(
            graph_data[adc_id]["ts"], graph_data[adc_id]["2"], label="2"
        )
        (line3,) = ax[0].plot(
            graph_data[adc_id]["ts"], graph_data[adc_id]["3"], label="3"
        )

        lines.append(line0)
        lines.append(line1)
        lines.append(line2)
        lines.append(line3)
        ax[0].legend(loc="upper left")

        # Format plot
        plt.xlim([0, max_samples])
        plt.grid(True)

    t = Thread(target=get_data, args=(max_samples,))
    t.start()

    # Set up plot to call animate() function periodically
    if args.adc == "all":
        interval = 200
    else:
        interval = 50

    ani = animation.FuncAnimation(
        fig,
        animate,
        init_func=init_plot,
        fargs=(graph_data,),
        interval=interval,
        blit=True,
        cache_frame_data=False,
    )

    # Blocks until closed
    plt.show()

    # Tell thread to end
    flag.change_state(0, 0)


if __name__ == "__main__":
    main()
