/* ftdi-uart: đọc/ghi UART kênh B của cáp FTDI 2232 (Tang Nano 4K: BL702 giả lập 0403:6010)
 * không cần driver ftdi_sio của kernel. Biên dịch tĩnh, chạy trên BPI-R3.
 *   ftdi-uart [-b baud] [-t giây] [-s "chuỗi gửi"] [-i]     (-i: gửi stdin, dừng khi EOF/hết giờ) */
#include <ftdi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>

int main(int argc, char **argv) {
    int baud = 115200, secs = 5, opt, use_stdin = 0;
    const char *send = NULL;
    while ((opt = getopt(argc, argv, "b:t:s:i")) != -1) switch (opt) {
        case 'b': baud = atoi(optarg); break;
        case 't': secs = atoi(optarg); break;
        case 's': send = optarg; break;
        case 'i': use_stdin = 1; break;
        default: fprintf(stderr, "dùng: %s [-b baud] [-t giây] [-s chuỗi] [-i]\n", argv[0]); return 2;
    }
    struct ftdi_context *f = ftdi_new();
    ftdi_set_interface(f, INTERFACE_B);
    if (ftdi_usb_open(f, 0x0403, 0x6010) < 0) { fprintf(stderr, "mở FTDI lỗi: %s\n", ftdi_get_error_string(f)); return 1; }
    ftdi_set_baudrate(f, baud);
    ftdi_set_line_property(f, BITS_8, STOP_BIT_1, NONE);
    ftdi_set_latency_timer(f, 2);
    ftdi_tcioflush(f);
    if (send) ftdi_write_data(f, (unsigned char *)send, strlen(send));
    if (use_stdin) fcntl(0, F_SETFL, O_NONBLOCK);
    time_t end = time(NULL) + secs;
    unsigned char buf[512];
    while (time(NULL) < end) {
        int n = ftdi_read_data(f, buf, sizeof buf);
        if (n < 0) { fprintf(stderr, "đọc lỗi: %s\n", ftdi_get_error_string(f)); break; }
        if (n) { fwrite(buf, 1, n, stdout); fflush(stdout); }
        if (use_stdin) {
            ssize_t m = read(0, buf, sizeof buf);
            if (m > 0) ftdi_write_data(f, buf, m);
        }
        if (!n) usleep(2000);
    }
    ftdi_usb_close(f); ftdi_free(f);
    return 0;
}
