package cwnu.dchw2.server;

import cwnu.dchw2.common.Interfaces;
import cwnu.dchw2.common.Protocol;
import java.util.ArrayDeque;
import java.util.Objects;
import java.util.concurrent.locks.Condition;
import java.util.concurrent.locks.ReentrantLock;

/** close는 입력만 닫는다. 이미 적재된 요청은 take로 끝까지 꺼낸다. */
public final class RequestQueue implements Interfaces.RequestQueue {
    private final ArrayDeque<Interfaces.Task> tasks = new ArrayDeque<>();
    private final ReentrantLock lock = new ReentrantLock();
    private final Condition notEmpty = lock.newCondition();
    private final Condition notFull = lock.newCondition();
    private final int capacity;
    private boolean closed;
    private int maxSize;

    public RequestQueue() {
        this(Protocol.REQUEST_QUEUE_CAPACITY);
    }

    public RequestQueue(int capacity) {
        if (capacity < 1) {
            throw new IllegalArgumentException("Queue 용량은 양수여야 합니다.");
        }
        this.capacity = capacity;
    }

    @Override
    public void put(Interfaces.Task task) throws InterruptedException {
        Objects.requireNonNull(task, "task");
        lock.lockInterruptibly();
        try {
            while (!closed && tasks.size() == capacity) {
                notFull.await();
            }
            if (closed) {
                throw new IllegalStateException("Request Queue 입력이 종료되었습니다.");
            }
            tasks.addLast(task);
            maxSize = Math.max(maxSize, tasks.size());
            notEmpty.signal();
        } finally {
            lock.unlock();
        }
    }

    @Override
    public Interfaces.Task take() throws InterruptedException {
        lock.lockInterruptibly();
        try {
            while (tasks.isEmpty() && !closed) {
                notEmpty.await();
            }
            if (tasks.isEmpty()) {
                return null;
            }
            Interfaces.Task task = tasks.removeFirst();
            notFull.signal();
            return task;
        } finally {
            lock.unlock();
        }
    }

    @Override
    public void close() {
        lock.lock();
        try {
            closed = true;
            notEmpty.signalAll();
            notFull.signalAll();
        } finally {
            lock.unlock();
        }
    }

    @Override
    public Interfaces.QueueView snapshot() {
        lock.lock();
        try {
            return new Interfaces.QueueView(tasks.size(), maxSize);
        } finally {
            lock.unlock();
        }
    }
}
