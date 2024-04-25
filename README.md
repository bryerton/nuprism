# nuprism

NuPRISM diagnostic script(s)

## Enabling Acquisition

telnet <ip> 40  # Port is 40

> stop_acquisition
> set_adc_mask 0x1F   # All channels
> get_adc_mask
> start_acquisition <ip> 1500 1  # <ip of client> <port> <ethernet device>
> set_num_samples_per_packet <num>
> get_num_samples_per_packet
